#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <functional>
#include <cstring>
#include <fstream>
#include <future>
#include <iostream>
#include <stdexcept>

#include "control.hpp"
#include "transport.hpp"
using namespace gufo::server;
using gufo::json::Value;
namespace {
struct State : TextRunnerState {
  std::size_t position = 0, sum = 0;
  std::optional<TextRunnerToken> pending;
  std::size_t sequence_size = 0;
  void Invalidate() noexcept override { position = sum = 0; }
};
struct Snapshot : TextRunnerSnapshot {
  std::array<std::uint64_t, 2> data;
  explicit Snapshot(const State& state) : data{state.position, state.sum} {}
  std::size_t PayloadBytes() const noexcept override { return sizeof(data); }
};
struct Runner : TextModelRunner {
  mutable std::size_t reads = 0, states_created = 0;
  bool fail_restore = false;
  std::function<void()> before_prefill;
  TextRunnerDescriptor Descriptor() const override {
    return {.model_id = "fake",
            .state_abi = "test-v1",
            .max_context = 256,
            .capabilities = {.incremental_prefill = true, .snapshot = true}};
  }
  TextRunnerResourceClaim ResourceClaim() const override { return {}; }
  std::vector<TextExecutionPlan> SupportedPlans() const override { return {}; }
  std::vector<TextRunnerToken> Tokenize(std::string_view text) const override {
    return {text.begin(), text.end()};
  }
  std::string Decode(std::span<const TextRunnerToken> tokens) const override {
    return {tokens.begin(), tokens.end()};
  }
  std::optional<std::vector<TextRunnerToken>> RenderAndTokenize(
      const ChatRequest& chat) const override {
    std::string rendered;
    for (const auto& message : chat.messages) {
      rendered += std::string(gufo::tokenization::ToString(message.role)) +
                  ":" + message.content + ":" + message.thought;
      for (const auto& call : message.tool_calls)
        rendered += ":" + call.name;
    }
    for (const auto& tool : chat.tools)
      rendered += ":tool=" + tool.name;
    rendered += "assistant\n<think>\n";
    return Tokenize(rendered);
  }
  TextGenerationBackend::InitialOutputState InitialOutputState(
      const ChatRequest&) const override {
    return TextGenerationBackend::InitialOutputState::kReasoning;
  }
  std::unique_ptr<TextRunnerState> CreateState() const override {
    ++states_created;
    return std::make_unique<State>();
  }
  TextPrefillStep Prefill(TextRunnerState& state,
                          std::span<const TextRunnerToken> prompt,
                          std::size_t offset,
                          std::size_t budget) const override {
    if (before_prefill)
      before_prefill();
    auto& s = dynamic_cast<State&>(state);
    if (s.position != offset)
      throw std::runtime_error("offset");
    auto n = std::min({budget, prompt.size() - offset, std::size_t(2)});
    for (auto token : prompt.subspan(offset, n)) {
      s.sum += token;
      ++s.position;
      ++reads;
    }
    return {.consumed_tokens = n, .decode_ready = s.position == prompt.size()};
  }
  TextDecodeSelection SelectNext(
      TextRunnerState& state,
      gufo::sampling::SamplerState& sampler) const override {
    std::array<float, 8> logits{0, 1, 2, 3, 4, 5, 6, 7};
    logits[dynamic_cast<State&>(state).sum % logits.size()] += 1;
    return {.token = sampler.Sample(logits)};
  }
  void Advance(TextRunnerState& state, TextRunnerToken token) const override {
    auto& s = dynamic_cast<State&>(state);
    s.sum += token;
    ++s.position;
  }
  std::size_t CheckpointPosition(const TextRunnerState& state) const override {
    return dynamic_cast<const State&>(state).position;
  }
  std::unique_ptr<TextRunnerSnapshot> Snapshot(
      const TextRunnerState& state) const override {
    return std::make_unique<struct Snapshot>(dynamic_cast<const State&>(state));
  }
  std::size_t PersistentSnapshotPayloadBytes(
      const TextRunnerSnapshot&) const override {
    return 16;
  }
  std::size_t SerializePersistentSnapshot(
      const TextRunnerSnapshot& snapshot,
      std::span<std::uint8_t> out) const override {
    if (out.size() != 16)
      throw std::runtime_error("size");
    std::memcpy(out.data(),
                dynamic_cast<const struct Snapshot&>(snapshot).data.data(), 16);
    return 16;
  }
  void RestorePersistentSnapshot(
      TextRunnerState& state, std::span<const std::uint8_t> in) const override {
    if (in.size() != 16)
      throw std::runtime_error("size");
    std::array<std::uint64_t, 2> data{};
    std::memcpy(data.data(), in.data(), 16);
    auto& s = dynamic_cast<State&>(state);
    s.position = data[0];
    s.sum = data[1];
    if (fail_restore)
      throw std::runtime_error("restore mutated then failed");
  }
};
// Mirror the native speculative contract: publish a block whose final token
// remains pending, and advance it with decode arithmetic at the outer boundary.
struct SpeculativeRunner : Runner {
  mutable std::size_t boundaries = 0;
  TextRunnerDescriptor Descriptor() const override {
    auto descriptor = Runner::Descriptor();
    descriptor.state_abi = "speculative-test-v1";
    descriptor.capabilities.multi_token_decode = true;
    return descriptor;
  }
  void PreparePrefixReuse(
      TextRunnerState& state,
      std::span<const TextRunnerToken> prefix) const override {
    PrepareContinuation(state, prefix);
    ++boundaries;
  }
  void PrepareContinuation(
      TextRunnerState& state,
      std::span<const TextRunnerToken> prefix) const override {
    if (CheckpointPosition(state) != prefix.size())
      throw std::runtime_error("bad speculative boundary");
    dynamic_cast<State&>(state).sequence_size = prefix.size();
  }
  TextPrefillStep Prefill(TextRunnerState& state,
                          std::span<const TextRunnerToken> prompt,
                          std::size_t offset,
                          std::size_t budget) const override {
    auto& s = dynamic_cast<State&>(state);
    if (!s.pending) {
      if (s.sequence_size != offset)
        throw std::runtime_error("speculative prefix index was not restored");
      const auto result = Runner::Prefill(state, prompt, offset, budget);
      s.sequence_size = s.position;
      return result;
    }
    if (offset != s.position || budget != 1 || prompt[offset] != *s.pending)
      throw std::runtime_error("pending token must use decode arithmetic");
    Advance(state, *s.pending);
    s.pending.reset();
    s.sequence_size = s.position;
    return {.consumed_tokens = 1, .decode_ready = true};
  }
  TextDecodeStep DecodeStep(
      TextRunnerState& state, std::size_t maximum,
      gufo::sampling::SamplerState& sampler) const override {
    auto& s = dynamic_cast<State&>(state);
    if (s.pending) {
      Advance(state, *s.pending);
      s.pending.reset();
    }
    auto working = sampler;
    TextDecodeStep result;
    const auto count = std::min(maximum, std::size_t(3));
    for (std::size_t i = 0; i < count; ++i) {
      auto selection = SelectNext(state, working);
      working.Accept(selection.token);
      if (i + 1 < count)
        Advance(state, selection.token);
      else
        s.pending = selection.token;
      result.selections.push_back(selection);
    }
    s.sequence_size =
        s.position + 1;  // the published pending token is logical history
    sampler.SetRngState(working.rng_state());
    result.draft_rounds = 1;
    result.draft_tokens = result.draft_accepted_tokens = count - 1;
    return result;
  }
};
void Check(bool value, const char* message) {
  if (!value)
    throw std::runtime_error(message);
}
Value Parse(const char* value) {
  return gufo::json::parse(value);
}
Value Step(std::size_t held, const Value& tokens, std::size_t count) {
  auto q = Value::object();
  q["op"] = "think";
  q["lane"] = 0;
  q["tokens"] = tokens;
  q["held"] = held;
  q["max_input_tokens"] = 4;
  q["max_new"] = count;
  q["sampling"] = Parse(
      R"({"temperature":0.8,"seed":123,"repeat_penalty":1.1,"frequency_penalty":0.2})");
  return q;
}
Value Append(Value a, const Value& b) {
  for (const auto& v : b.items())
    a.push_back(v);
  return a;
}
}  // namespace
int main() {
  auto path = std::filesystem::temp_directory_path() /
              ("gufo-control-test-" + std::to_string(getpid()));
  try {
    {
      auto speculative = std::make_shared<SpeculativeRunner>();
      cointos::Control controlled(speculative, 1, path / "spec", "draft-A");
      const auto prompt = Parse("[11,12,13]");
      const auto first = controlled.Call(Step(0, prompt, 7));
      const auto history = Append(prompt, *first.find("tokens"));
      Check(first.member_size("held") == history.size(),
            "speculative tokens did not become exact held state");
      Check(speculative->reads == 3, "speculative boundary reread the prompt");
      Check(speculative->boundaries == 0,
            "scheduler chunk reset request-local speculative policy");
      Check(first.member_size("draft_rounds") == 3,
            "speculative rounds were not accounted");
      controlled.Call(Parse(R"({"op":"save","lane":0,"name":"spec"})"));
      const auto expected = controlled.Call(Step(history.size(), history, 8));
      Check(speculative->boundaries == 0,
            "continued response reset request-local speculative policy");
      // Extend an in-memory decoded history directly, as reasoning closure
      // and tool-result insertion do, without a restore reattaching its index.
      const auto continued = Append(history, *expected.find("tokens"));
      const auto extended_tokens = Append(continued, Parse("[19]"));
      const auto extended_step =
          controlled.Call(Step(continued.size(), extended_tokens, 1));
      Check(extended_step.member_size("held") == extended_tokens.size() + 1,
            "decoded continuation could not accept a prompt suffix");
      Check(speculative->boundaries == 0,
            "prompt extension used a request reset to repair its token index");
      cointos::Control restored(speculative, 1, path / "spec", "draft-A");
      restored.Call(Parse(R"({"op":"restore","lane":0,"name":"spec"})"));
      const auto replay = restored.Call(Step(history.size(), history, 8));
      Check(speculative->boundaries == 0,
            "snapshot continuation reset request-local speculative policy");
      Check(expected.find("tokens")->dump() == replay.find("tokens")->dump(),
            "sampled speculative boundary changed after disk restore");
      // The scheduler restores a partial read and then appends the remaining
      // prompt. Decode-only restore checks do not exercise this path.
      const auto prefix_step = controlled.Call(Step(0, prompt, 1));
      const auto prefix_tokens = Append(prompt, *prefix_step.find("tokens"));
      controlled.Call(Parse(R"({"op":"save","lane":0,"name":"prefix"})"));
      cointos::Control extended(speculative, 1, path / "spec", "draft-A");
      extended.Call(Parse(R"({"op":"restore","lane":0,"name":"prefix"})"));
      const auto continuation =
          extended.Call(Step(4, Append(prefix_tokens, Parse("[19]")), 1));
      Check(continuation.member_size("held") == 6,
            "restored speculative prefix could not extend");
    }
    {
      auto reusable = std::make_shared<Runner>();
      cointos::Control controlled(reusable, 1, path / "reuse", "model-A");
      const auto prompt = Parse("[11,12,13]");
      const auto first = controlled.Call(Step(0, prompt, 1));
      const auto history = Append(prompt, *first.find("tokens"));
      controlled.Call(Parse(R"({"op":"save","lane":0,"name":"state"})"));
      for (int i = 0; i < 5; ++i)
        controlled.Call(Parse(R"({"op":"restore","lane":0,"name":"state"})"));
      Check(reusable->states_created == 1,
            "restore recreated the physical executor");
      reusable->fail_restore = true;
      bool failed = false;
      try {
        controlled.Call(Parse(R"({"op":"restore","lane":0,"name":"state"})"));
      } catch (...) {
        failed = true;
      }
      reusable->fail_restore = false;
      Check(failed, "native restore failure was ignored");
      bool lost = false;
      try {
        controlled.Call(Step(history.size(), history, 1));
      } catch (const std::exception& error) {
        lost = std::string(error.what()).starts_with("lost:");
      }
      Check(lost, "failed in-place restore retained stale lane metadata");
      Check(controlled.Call(Step(0, prompt, 1)).member_size("held") == 4,
            "failed restore prevented a fresh request");
    }
    auto runner = std::make_shared<Runner>();
    cointos::Control control(runner, 2, path, "model-A");
    auto tokens = Parse("[11,12,13]");
    auto first = control.Call(Step(0, tokens, 4));
    tokens = Append(tokens, *first.find("tokens"));
    Check(first.member_size("held") == 7 && runner->reads == 3,
          "bounded read/decode");
    control.Call(Parse(R"({"op":"save","lane":0,"name":"saved"})"));
    auto second = control.Call(Step(7, tokens, 8));
    // A new controller must restore native state from the file, without an
    // in-memory cache.
    cointos::Control restarted(runner, 2, path, "model-A");
    restarted.Call(Parse(R"({"op":"restore","lane":0,"name":"saved"})"));
    auto replay = restarted.Call(Step(7, tokens, 8));
    Check(replay.find("tokens")->dump() == second.find("tokens")->dump(),
          "sampled disk continuation changed");
    Check(runner->reads == 3, "restored prefix was reread");
    auto bad = Step(7, Parse("[99,12,13,1,2,3,4]"), 1);
    bool lost = false;
    try {
      restarted.Call(bad);
    } catch (const std::exception& e) {
      lost = std::string(e.what()).starts_with("lost:");
    }
    Check(lost && runner->reads == 3, "lost cache read work before rejection");
    bool budget = false;
    try {
      restarted.Call(Step(0, Parse("[1,2,3,4,5]"), 1));
    } catch (...) {
      budget = true;
    }
    Check(budget && runner->reads == 3, "unbounded prefill accepted");
    cointos::Control other(runner, 1, path, "model-B");
    bool mismatch = false;
    try {
      other.Call(Parse(R"({"op":"restore","lane":0,"name":"saved"})"));
    } catch (...) {
      mismatch = true;
    }
    Check(mismatch, "wrong model snapshot accepted");
    std::fstream damaged(path / "saved.bin",
                         std::ios::in | std::ios::out | std::ios::binary);
    damaged.seekg(-1, std::ios::end);
    const char original = damaged.get();
    damaged.seekp(-1, std::ios::end);
    damaged.put(original ^ 1);
    damaged.close();
    bool corrupt = false;
    try {
      restarted.Call(Parse(R"({"op":"restore","lane":0,"name":"saved"})"));
    } catch (...) {
      corrupt = true;
    }
    Check(corrupt, "corrupt snapshot accepted");
    auto render = control.Call(Parse(
        R"({"op":"render","messages":[{"role":"user","content":"hi"},{"role":"assistant","reasoning_content":"partial","content":""}],"continue_final_message":true,"tools":[{"type":"function","function":{"name":"lookup","parameters":{"type":"object"}}}]})"));
    Check(render.member_str("prompt").ends_with("<think>\npartial"),
          "continuation framing");
    Check(render.member_str("prompt").find("tool=lookup") != std::string::npos,
          "tool declarations lost");
    auto history = control.Call(Parse(
        R"({"op":"render","messages":[{"role":"user","content":"hi"},{"role":"assistant","content":null,"tool_calls":[{"id":"x","type":"function","function":{"name":"lookup","arguments":"{\"x\":true}"}}]},{"role":"tool","tool_call_id":"x","content":"ok"}]})"));
    Check(history.member_str("prompt").find(":lookup") != std::string::npos,
          "tool history lost");
    auto unicode = control.Call(Parse(R"({"op":"text","tokens":[240,159]})"));
    Check(unicode.member_str("content") == "\xef\xbf\xbd",
          "partial UTF-8 broke JSON output");
    auto complete =
        control.Call(Parse(R"({"op":"text","tokens":[240,159,166,166]})"));
    Check(complete.member_str("content") == "🦦", "complete UTF-8 was changed");
    const auto socket_path = (path / "test.sock").string();
    int listener = socket(AF_UNIX, SOCK_STREAM, 0);
    sockaddr_un address{};
    address.sun_family = AF_UNIX;
    std::memcpy(address.sun_path, socket_path.c_str(), socket_path.size() + 1);
    Check(bind(listener, reinterpret_cast<sockaddr*>(&address),
               sizeof(address)) == 0 &&
              listen(listener, 5) == 0,
          "test socket bind");
    auto socket_runner = std::make_shared<Runner>();
    cointos::Control socket_control(socket_runner, 2, path / "socket", "socket");
    auto server = std::async(std::launch::async, [&] {
      cointos::ServeControl(listener, socket_control);
    });
    auto rpc = [&](const std::string& request) {
      int client = socket(AF_UNIX, SOCK_STREAM, 0);
      Check(connect(client, reinterpret_cast<sockaddr*>(&address),
                    sizeof(address)) == 0,
            "test socket connect");
      auto bytes = request + "\n";
      Check(write(client, bytes.data(), bytes.size()) ==
                static_cast<ssize_t>(bytes.size()),
            "test socket write");
      std::string line;
      char buffer[4096];
      while (line.find('\n') == std::string::npos) {
        auto n = read(client, buffer, sizeof(buffer));
        Check(n > 0, "test socket response");
        line.append(buffer, n);
      }
      close(client);
      return gufo::json::parse(line);
    };
    Check(rpc(R"({"op":"info"})").find("result")->member_size("context") == 256,
          "native socket health");
    Check(rpc(R"({"op":"text","tokens":[240,159]})")
                  .find("result")
                  ->member_str("content") == "\xef\xbf\xbd",
          "native socket UTF-8");
    Check(
        rpc(R"({"op":"prefill","lane":1,"tokens":[1],"held":1,"max_input_tokens":1})")
            .member_str("error")
            .starts_with("lost:"),
        "native socket errors");
    // Hold a model operation inside the runner. Metadata must finish before
    // release, while a second lane-state operation must remain behind it.
    std::promise<void> entered, release;
    auto entered_future = entered.get_future();
    auto release_future = release.get_future().share();
    std::atomic<bool> first_prefill{true};
    socket_runner->before_prefill = [&] {
      if (first_prefill.exchange(false)) {
        entered.set_value();
        release_future.wait();
      }
    };
    auto reading = std::async(std::launch::async, [&] {
      return rpc(R"({"op":"prefill","lane":0,"tokens":[1,2],"held":0,"max_input_tokens":2})");
    });
    const bool model_entered =
        entered_future.wait_for(std::chrono::seconds(2)) == std::future_status::ready;
    auto metadata = std::async(std::launch::async, [&] {
      auto results = Value::array();
      results.push_back(rpc(R"({"op":"info"})"));
      results.push_back(rpc(R"({"op":"text","tokens":[240,159,166,166]})"));
      results.push_back(rpc(R"({"op":"tokenize","text":"probe"})"));
      results.push_back(rpc(R"({"op":"render","messages":[{"role":"user","content":"probe"}]})"));
      return results;
    });
    auto next_read = std::async(std::launch::async, [&] {
      return rpc(R"({"op":"prefill","lane":0,"tokens":[1,2,3],"held":2,"max_input_tokens":1})");
    });
    const bool metadata_ready =
        metadata.wait_for(std::chrono::seconds(2)) == std::future_status::ready;
    const bool model_serial =
        next_read.wait_for(std::chrono::milliseconds(50)) == std::future_status::timeout;
    // Always release before asserting, so the old serialized implementation
    // fails the test rather than hanging its future/server destructors.
    release.set_value();
    auto answers = metadata.get();
    const auto first_read = reading.get();
    const auto second_read = next_read.get();
    const auto stopped = rpc(R"({"op":"shutdown"})");
    server.get();
    close(listener);
    Check(model_entered && metadata_ready, "metadata waited behind inference ownership");
    Check(model_serial && first_read.find("result")->member_size("held") == 2 &&
              second_read.find("result")->member_size("held") == 3,
          "mutable model operations lost serial ownership");
    Check(answers.items().size() == 4 &&
              std::all_of(answers.items().begin(), answers.items().end(),
                          [](const auto& answer) { return answer.contains("result"); }),
          "concurrent metadata returned an error");
    Check(answers.items()[1].find("result")->member_str("content") == "🦦" &&
              answers.items()[2].find("result")->find("tokens")->size() == 5 &&
              answers.items()[3].find("result")->member_str("prompt").find("probe") != std::string::npos,
          "concurrent metadata changed content or framing");
    bool metadata_refused_model = false;
    try {
      socket_control.Metadata(Parse(R"({"op":"prefill","lane":0})"));
    } catch (const std::invalid_argument&) {
      metadata_refused_model = true;
    }
    Check(metadata_refused_model, "metadata endpoint admitted a mutable operation");
    Check(stopped.find("ok")->as_bool(), "native socket shutdown");
    std::filesystem::remove_all(path);
    std::cout << "native control contract passed\n";
    return 0;
  } catch (const std::exception& e) {
    std::filesystem::remove_all(path);
    std::cerr << e.what() << '\n';
    return 1;
  }
}
