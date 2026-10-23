#include "control.hpp"

#include <fcntl.h>
#include <openssl/evp.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstring>
#include <fstream>
#include <limits>
#include <stdexcept>

#include "src/cli/serve/openai_chat.hpp"
#include "src/cli/serve/sampling_request.hpp"
#include "src/core/utf8.hpp"

namespace cointos {
using gufo::json::Value;
using gufo::server::TextRunnerToken;
namespace {
std::size_t Integer(const Value& value, const std::string& name) {
  const auto* v = value.find(name);
  if (!v || !v->is_number() || !std::isfinite(v->as_double()) ||
      v->as_double() < 0 || std::floor(v->as_double()) != v->as_double() ||
      v->as_double() > std::numeric_limits<std::uint32_t>::max())
    throw std::invalid_argument("invalid integer: " + name);
  return v->as_size();
}
std::vector<TextRunnerToken> Tokens(const Value& value) {
  if (!value.is_array())
    throw std::invalid_argument("tokens must be an array");
  std::vector<TextRunnerToken> tokens;
  for (const auto& item : value.items()) {
    Value wrapper = Value::object();
    wrapper["token"] = item;
    tokens.push_back(static_cast<TextRunnerToken>(Integer(wrapper, "token")));
  }
  return tokens;
}
Value JsonTokens(std::span<const TextRunnerToken> tokens) {
  auto result = Value::array();
  for (auto token : tokens)
    result.push_back(static_cast<std::size_t>(token));
  return result;
}
const Value& Required(const Value& value, const std::string& name) {
  const auto* result = value.find(name);
  if (!result)
    throw std::invalid_argument("missing " + name);
  return *result;
}
std::filesystem::path SnapshotPath(const std::filesystem::path& dir,
                                   const std::string& name) {
  if (name.empty() || name == "." || name == ".." ||
      name.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVW"
                             "XYZ0123456789._-") != std::string::npos)
    throw std::invalid_argument("invalid snapshot name");
  return dir / (name + ".bin");
}
struct Digest {
  EVP_MD_CTX* ctx = EVP_MD_CTX_new();
  Digest() {
    if (!ctx || EVP_DigestInit_ex(ctx, EVP_sha256(), nullptr) != 1)
      throw std::runtime_error("SHA256 init failed");
  }
  ~Digest() { EVP_MD_CTX_free(ctx); }
  void Add(const void* p, std::size_t n) {
    if (EVP_DigestUpdate(ctx, p, n) != 1)
      throw std::runtime_error("SHA256 update failed");
  }
  std::array<unsigned char, 32> Finish() {
    std::array<unsigned char, 32> out{};
    unsigned int n = 0;
    if (EVP_DigestFinal_ex(ctx, out.data(), &n) != 1 || n != out.size())
      throw std::runtime_error("SHA256 failed");
    return out;
  }
};
struct SnapshotMapping {
  void* data = MAP_FAILED;
  std::size_t size;
  SnapshotMapping(int descriptor, std::size_t bytes) : size(bytes) {
    if (ftruncate(descriptor, bytes))
      throw std::runtime_error("snapshot allocation failed");
    data =
        mmap(nullptr, bytes, PROT_READ | PROT_WRITE, MAP_SHARED, descriptor, 0);
    if (data == MAP_FAILED)
      throw std::runtime_error("snapshot mapping failed");
  }
  ~SnapshotMapping() {
    if (data != MAP_FAILED)
      munmap(data, size);
  }
};
struct Mapping {
  int fd = -1;
  void* data = MAP_FAILED;
  std::size_t size = 0;
  explicit Mapping(const std::filesystem::path& path) {
    fd = open(path.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0)
      throw std::runtime_error("cannot open snapshot");
    struct stat st {};
    if (fstat(fd, &st) || !S_ISREG(st.st_mode) || st.st_size <= 32) {
      close(fd);
      fd = -1;
      throw std::runtime_error("invalid snapshot size");
    }
    size = st.st_size;
    data = mmap(nullptr, size, PROT_READ, MAP_PRIVATE, fd, 0);
    if (data == MAP_FAILED) {
      close(fd);
      fd = -1;
      throw std::runtime_error("cannot map snapshot");
    }
  }
  ~Mapping() {
    if (data != MAP_FAILED)
      munmap(data, size);
    if (fd >= 0)
      close(fd);
  }
};
}  // namespace
std::string FileSha256(const std::filesystem::path& path) {
  std::ifstream input(path, std::ios::binary);
  if (!input)
    throw std::runtime_error("cannot open model for hashing");
  Digest digest;
  std::array<char, 1024 * 1024> buffer{};
  while (input.read(buffer.data(), buffer.size()) || input.gcount())
    digest.Add(buffer.data(), input.gcount());
  if (!input.eof())
    throw std::runtime_error("model hash read failed");
  const auto bytes = digest.Finish();
  const char* hex = "0123456789abcdef";
  std::string result;
  for (auto b : bytes) {
    result += hex[b >> 4];
    result += hex[b & 15];
  }
  return result;
}
Control::Control(std::shared_ptr<const gufo::server::TextModelRunner> runner,
                 std::size_t lanes, std::filesystem::path snapshots,
                 std::string identity)
    : runner_(std::move(runner)),
      lanes_(lanes),
      snapshots_(std::move(snapshots)),
      identity_(std::move(identity)) {
  if (!runner_ || lanes == 0)
    throw std::invalid_argument("runner and lanes required");
  identity_ += ":" + runner_->Descriptor().state_abi + ":" +
               std::to_string(runner_->Descriptor().max_context) +
               ":control-v1";
  std::filesystem::create_directories(snapshots_);
}
Value Control::Render(const Value& request) const {
  gufo::server::ChatRequest chat;
  if (auto error = gufo::server::ParseControlChat(request, &chat))
    throw std::invalid_argument(*error);
  const auto* continuation = request.find("continue_final_message");
  const bool resume = continuation && continuation->as_bool();
  std::optional<gufo::tokenization::ChatMessage> tail;
  if (resume) {
    if (chat.messages.back().role != gufo::tokenization::ChatRole::kAssistant ||
        !chat.messages.back().tool_calls.empty())
      throw std::invalid_argument(
          "continuation requires an assistant text tail");
    tail = std::move(chat.messages.back());
    chat.messages.pop_back();
  } else if (chat.messages.back().role ==
                 gufo::tokenization::ChatRole::kAssistant &&
             chat.messages.back().content.empty() &&
             chat.messages.back().thought.empty() &&
             chat.messages.back().tool_calls.empty()) {
    chat.messages.pop_back();
  }
  auto rendered = runner_->RenderAndTokenize(chat);
  if (!rendered)
    throw std::invalid_argument("native chat rendering failed");
  if (tail) {
    std::string suffix = tail->thought;
    if (!tail->content.empty()) {
      if (runner_->InitialOutputState(chat) ==
          gufo::server::TextGenerationBackend::InitialOutputState::kReasoning)
        suffix += "\n</think>\n\n";
      suffix += tail->content;
    }
    auto extra = runner_->Tokenize(suffix);
    rendered->insert(rendered->end(), extra.begin(), extra.end());
  }
  auto result = Value::object();
  result["tokens"] = JsonTokens(*rendered);
  result["prompt"] = runner_->Decode(*rendered);
  return result;
}
void Control::Prefill(Lane& lane, const Value& request) {
  auto tokens = Tokens(Required(request, "tokens"));
  const auto held = Integer(request, "held");
  const auto budget = Integer(request, "max_input_tokens");
  if (tokens.empty() || tokens.size() > runner_->Descriptor().max_context ||
      held > tokens.size())
    throw std::invalid_argument("invalid context length");
  if (held > lane.tokens.size() ||
      !std::equal(tokens.begin(), tokens.begin() + held, lane.tokens.begin()))
    throw std::runtime_error("lost: lane does not retain the declared prefix");
  if (!lane.state || lane.tokens.size() > tokens.size() ||
      !std::equal(lane.tokens.begin(), lane.tokens.end(), tokens.begin())) {
    if (held)
      throw std::runtime_error("lost: lane cannot rewind hybrid state");
    lane = Lane{};
    lane.state = runner_->CreateState();
  }
  if (tokens.size() - lane.tokens.size() > budget)
    throw std::invalid_argument("prefill exceeds its input budget");
  if (lane.tokens.size() != tokens.size())
    lane.sampler.reset();
  while (lane.tokens.size() < tokens.size()) {
    auto step = runner_->Prefill(*lane.state, tokens, lane.tokens.size(),
                                 tokens.size() - lane.tokens.size());
    if (step.consumed_tokens == 0 ||
        step.consumed_tokens > tokens.size() - lane.tokens.size())
      throw std::runtime_error("invalid native prefill progress");
    lane.tokens.insert(
        lane.tokens.end(), tokens.begin() + lane.tokens.size(),
        tokens.begin() + lane.tokens.size() + step.consumed_tokens);
    if (runner_->CheckpointPosition(*lane.state) != lane.tokens.size())
      throw std::runtime_error("native prefill position mismatch");
  }
}
Value Control::Save(Lane& lane, const std::string& name) {
  if (!lane.state || lane.tokens.empty())
    throw std::runtime_error("empty lane");
  auto snapshot = runner_->SnapshotForPersistence(*lane.state);
  const auto bytes = runner_->PersistentSnapshotPayloadBytes(*snapshot);
  auto header = Value::object();
  header["identity"] = identity_;
  header["tokens"] = JsonTokens(lane.tokens);
  header["bytes"] = bytes;
  if (lane.sampler) {
    header["sampling"] = lane.sampling;
    header["prompt_size"] = lane.prompt_size;
    const auto draw = lane.sampler->SaveDrawState();
    header["rng"] = std::to_string(draw.rng);
    if (draw.pending)
      header["pending"] = static_cast<std::size_t>(*draw.pending);
  }
  auto path = SnapshotPath(snapshots_, name);
  auto temp = path;
  temp += ".tmp." + std::to_string(getpid());
  // Directory and transport are private to the CointOS user; publish only
  // complete files.
  // An interrupted write releases its anonymous inode, including on tmpfs.
  int fd = open(snapshots_.c_str(), O_TMPFILE | O_RDWR | O_CLOEXEC, 0600);
  if (fd < 0)
    throw std::runtime_error("cannot create snapshot");
  try {
    const auto line = header.dump() + "\n";
    if (bytes > std::numeric_limits<std::size_t>::max() - line.size() - 32)
      throw std::overflow_error("snapshot size overflow");
    // Serialize into the cache file itself: no full-size host staging vector.
    SnapshotMapping mapping(fd, line.size() + bytes + 32);
    auto* destination = static_cast<std::uint8_t*>(mapping.data);
    std::memcpy(destination, line.data(), line.size());
    if (runner_->SerializePersistentSnapshot(
            *snapshot, {destination + line.size(), bytes}) != bytes)
      throw std::runtime_error("native snapshot was incomplete");
    Digest digest;
    digest.Add(destination, line.size() + bytes);
    const auto checksum = digest.Finish();
    std::memcpy(destination + line.size() + bytes, checksum.data(),
                checksum.size());
    if (msync(mapping.data, mapping.size, MS_SYNC))
      throw std::runtime_error("snapshot sync failed");
    if (fsync(fd))
      throw std::runtime_error("snapshot fsync failed");
    const auto descriptor_path = "/proc/self/fd/" + std::to_string(fd);
    if (linkat(AT_FDCWD, descriptor_path.c_str(), AT_FDCWD, temp.c_str(),
               AT_SYMLINK_FOLLOW))
      throw std::runtime_error("snapshot publication failed");
    close(fd);
    fd = -1;
    std::filesystem::rename(temp, path);
    int directory =
        open(snapshots_.c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (directory < 0)
      throw std::runtime_error("snapshot directory open failed");
    const int sync_error = fsync(directory);
    close(directory);
    if (sync_error)
      throw std::runtime_error("snapshot directory fsync failed");
  } catch (...) {
    if (fd >= 0)
      close(fd);
    std::filesystem::remove(temp);
    throw;
  }
  auto result = Value::object();
  result["tokens"] = lane.tokens.size();
  result["bytes"] = std::filesystem::file_size(path);
  return result;
}
Value Control::Restore(Lane& lane, const std::string& name) {
  Mapping map(SnapshotPath(snapshots_, name));
  auto* begin = static_cast<const std::uint8_t*>(map.data);
  Digest digest;
  digest.Add(begin, map.size - 32);
  auto checksum = digest.Finish();
  if (std::memcmp(checksum.data(), begin + map.size - 32, 32))
    throw std::runtime_error("snapshot checksum mismatch");
  auto* newline =
      static_cast<const std::uint8_t*>(std::memchr(begin, '\n', map.size - 32));
  if (!newline)
    throw std::runtime_error("missing snapshot header");
  auto header = gufo::json::parse(
      std::string_view(reinterpret_cast<const char*>(begin), newline - begin));
  if (header.member_str("identity") != identity_)
    throw std::runtime_error("snapshot model/ABI mismatch");
  auto tokens = Tokens(Required(header, "tokens"));
  auto offset = static_cast<std::size_t>(newline - begin + 1);
  if (tokens.empty() || tokens.size() > runner_->Descriptor().max_context ||
      header.member_size("bytes") != map.size - offset - 32)
    throw std::runtime_error("invalid snapshot metadata");
  Lane restored;
  // Restore into the lane's existing executor, as the native continuation pool
  // does. Recreating it on every switch reallocates the full target/draft GPU
  // session. Leave the lane empty until the whole restore succeeds: a native
  // restore may mutate its executor before throwing.
  restored.state = std::move(lane.state);
  lane = Lane{};
  if (restored.state)
    restored.state->Invalidate();
  else
    restored.state = runner_->CreateState();
  runner_->RestorePersistentSnapshot(*restored.state,
                                     {begin + offset, map.size - offset - 32});
  if (runner_->CheckpointPosition(*restored.state) != tokens.size())
    throw std::runtime_error("snapshot position mismatch");
  // Native persistence restores target/draft tensors, not the model runner's
  // request-local token index. Reattach this exact continuation without
  // beginning a different request and resetting the saved draft policy.
  runner_->PrepareContinuation(*restored.state, tokens);
  restored.tokens = std::move(tokens);
  if (const auto* sampling = header.find("sampling")) {
    gufo::sampling::SamplingConfig config;
    if (auto error = gufo::server::ParseSamplingConfig(*sampling, {}, &config))
      throw std::runtime_error(error->message);
    restored.prompt_size = Integer(header, "prompt_size");
    if (restored.prompt_size > restored.tokens.size())
      throw std::runtime_error("invalid sampler history");
    restored.sampling = *sampling;
    restored.sampler.emplace(
        config, std::span(restored.tokens).first(restored.prompt_size));
    restored.sampler->Accept(
        std::span(restored.tokens).subspan(restored.prompt_size));
    gufo::sampling::SamplerState::DrawState draw{
        std::stoull(header.member_str("rng")), std::nullopt};
    if (header.contains("pending"))
      draw.pending = static_cast<TextRunnerToken>(Integer(header, "pending"));
    restored.sampler->RestoreDrawState(draw);
  }
  lane = std::move(restored);
  auto result = Value::object();
  result["tokens"] = lane.tokens.size();
  return result;
}
Value Control::Metadata(const Value& request) const {
  const auto op = request.member_str("op");
  auto result = Value::object();
  if (op == "info") {
    result["protocol"] = 1;
    result["pid"] = static_cast<std::size_t>(getpid());
    result["identity"] = identity_;
    result["lanes"] = lanes_.size();
    result["context"] =
        static_cast<std::size_t>(runner_->Descriptor().max_context);
    result["speculative"] =
        runner_->Descriptor().capabilities.multi_token_decode;
    return result;
  }
  if (op == "render")
    return Render(request);
  if (op == "tokenize") {
    result["tokens"] =
        JsonTokens(runner_->Tokenize(request.member_str("text")));
    return result;
  }
  if (op == "text") {
    result["content"] = gufo::core::Utf8Decoder{}.Push(
        runner_->Decode(Tokens(Required(request, "tokens"))), true);
    return result;
  }
  throw std::invalid_argument("operation requires model ownership");
}
Value Control::Call(const Value& request) {
  const auto op = request.member_str("op");
  if (IsMetadata(op))
    return Metadata(request);
  auto result = Value::object();
  auto& lane = lanes_.at(Integer(request, "lane"));
  if (op == "save")
    return Save(lane, request.member_str("name"));
  if (op == "restore")
    return Restore(lane, request.member_str("name"));
  if (op == "prefill" || op == "think") {
    try {
      Prefill(lane, request);
      if (op == "prefill") {
        result["held"] = lane.tokens.size();
        return result;
      }
      const auto max_new = Integer(request, "max_new");
      if (max_new == 0 ||
          max_new > runner_->Descriptor().max_context - lane.tokens.size())
        throw std::invalid_argument("invalid decode budget");
      const auto& sampling = Required(request, "sampling");
      if (!lane.sampler || lane.sampling.dump() != sampling.dump()) {
        gufo::sampling::SamplingConfig config;
        if (auto error =
                gufo::server::ParseSamplingConfig(sampling, {}, &config))
          throw std::invalid_argument(error->message);
        lane.sampler.emplace(config, lane.tokens);
        lane.sampling = sampling;
        lane.prompt_size = lane.tokens.size();
      }
      const auto start = std::chrono::steady_clock::now();
      std::vector<TextRunnerToken> fresh;
      std::size_t rounds = 0, proposed = 0, accepted = 0;
      bool done = false;
      while (fresh.size() < max_new) {
        auto step = runner_->DecodeStep(*lane.state, max_new - fresh.size(),
                                        *lane.sampler);
        if (step.failure)
          std::rethrow_exception(step.failure);
        rounds += step.draft_rounds;
        proposed += step.draft_tokens;
        accepted += step.draft_accepted_tokens;
        if (step.selections.size() > max_new - fresh.size())
          throw std::runtime_error("native decode exceeded budget");
        for (const auto& selection : step.selections) {
          fresh.push_back(selection.token);
          lane.tokens.push_back(selection.token);
          lane.sampler->Accept(selection.token);
        }
        const auto position = runner_->CheckpointPosition(*lane.state);
        if (position > lane.tokens.size() ||
            lane.tokens.size() - position >
                (runner_->Descriptor().capabilities.multi_token_decode ? 1U
                                                                       : 0U))
          throw std::runtime_error("native decode position mismatch");
        if (step.stop) {
          done = true;
          break;
        }
        if (step.selections.empty())
          throw std::runtime_error("native decode made no progress");
      }
      // DFlash publishes its last selected token as an unconsumed frontier.
      // Materialize only that token once per external scheduler chunk, using
      // decode arithmetic. The saved state then holds exactly the published
      // token vector, just like AR, without replaying the generated history.
      const auto position = runner_->CheckpointPosition(*lane.state);
      if (position < lane.tokens.size()) {
        const auto advanced =
            runner_->Prefill(*lane.state, lane.tokens, position, 1);
        if (advanced.consumed_tokens != 1 ||
            runner_->CheckpointPosition(*lane.state) != lane.tokens.size())
          throw std::runtime_error("native pending-token advance mismatch");
      }
      result["tokens"] = JsonTokens(fresh);
      result["draft_rounds"] = rounds;
      result["draft_tokens"] = proposed;
      result["draft_accepted_tokens"] = accepted;
      result["held"] = lane.tokens.size();
      result["done"] = done;
      result["generation_seconds"] =
          std::chrono::duration<double>(std::chrono::steady_clock::now() -
                                        start)
              .count();
      return result;
    } catch (const std::exception& error) {
      if (!std::string_view(error.what()).starts_with("lost:"))
        lane = Lane{};
      throw;
    }
  }
  throw std::invalid_argument("unknown control operation");
}
}  // namespace cointos
