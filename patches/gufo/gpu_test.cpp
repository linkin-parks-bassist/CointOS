// Native HIP continuation through the actual Qwen runner, with small seeded
// weights.
#include <hip/hip_runtime.h>
#include <unistd.h>

#include <algorithm>
#include <filesystem>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <vector>

#include "control.hpp"
#include "src/cli/serve/inference_backend.hpp"
#include "src/models/qwen/control_tokens.hpp"
#include "src/models/qwen/hip/executor.hpp"
#include "tests/models/qwen/support/synthetic_weights.hpp"

namespace {
using gufo::json::Value;
void Check(bool condition, const std::string& message) {
  if (!condition)
    throw std::runtime_error(message);
}
void Hip(hipError_t error) {
  Check(error == hipSuccess, hipGetErrorString(error));
}
struct DevicePool {
  void* bytes = nullptr;
  ~DevicePool() {
    if (bytes)
      (void)hipFree(bytes);
  }
};
struct Fixture {
  DevicePool pool;
  std::shared_ptr<const gufo::hip::QwenGpuModel> model;
  Fixture() {
    auto config = gufo::models::qwen::make_small_qwen_config();
    config.context_length = 256;
    config.ssm_group_count = 1;
    auto synthetic = gufo::models::qwen::build_synthetic_qwen_weights(config);
    const auto size = synthetic.pool.size() * sizeof(float);
    Hip(hipMalloc(&pool.bytes, size));
    Hip(hipMemcpy(pool.bytes, synthetic.pool.data(), size,
                  hipMemcpyHostToDevice));
    auto weights = synthetic.weights;
    const auto remap = [&](gufo::models::QwenTensorRef& tensor) {
      if (tensor.empty())
        return;
      const auto offset =
          static_cast<const float*>(tensor.data) - synthetic.pool.data();
      tensor.data = static_cast<float*>(pool.bytes) + offset;
    };
    remap(weights.token_embd);
    remap(weights.output);
    remap(weights.output_norm);
    for (auto& layer : weights.layers) {
      for (auto* tensor :
           {&layer.attn_norm,   &layer.ffn_norm,    &layer.attn_q,
            &layer.attn_k,      &layer.attn_v,      &layer.attn_output,
            &layer.attn_q_norm, &layer.attn_k_norm, &layer.attn_qkv,
            &layer.attn_gate,   &layer.ssm_a,       &layer.ssm_conv1d,
            &layer.ssm_dt,      &layer.ssm_alpha,   &layer.ssm_beta,
            &layer.ssm_norm,    &layer.ssm_out,     &layer.ffn_gate,
            &layer.ffn_up,      &layer.ffn_down})
        remap(*tensor);
    }
    std::vector<std::string> vocabulary;
    for (std::size_t i = 0; i < config.vocab_size; ++i)
      vocabulary.push_back("word" + std::to_string(i));
    vocabulary.back() = gufo::tokenization::kImEnd;
    auto tokenizer = gufo::tokenization::QwenTokenizer::CreateFromVocabulary(
        vocabulary, {},
        {{std::string(gufo::tokenization::kImEnd), config.vocab_size - 1}});
    Check(tokenizer != nullptr, "fixture tokenizer");
    model = std::make_shared<const gufo::hip::QwenGpuModel>(
        nullptr, std::move(weights), std::move(tokenizer),
        std::vector<gufo::hip::QwenGpuWeightRegion>{
            {.device_data = pool.bytes, .size = size}});
  }
  std::shared_ptr<const gufo::server::TextModelRunner> Runner() {
    gufo::server::InferenceBackend backend;
    std::string error;
    Check(backend.load(model, &error, 256, 2), error);
    return backend.release_runner();
  }
};
Value Parse(const char* text) {
  return gufo::json::parse(text);
}
Value Step(std::size_t lane, const Value& tokens, std::size_t held,
           std::size_t count) {
  auto request = Value::object();
  request["op"] = "think";
  request["lane"] = lane;
  request["tokens"] = tokens;
  request["held"] = held;
  request["max_new"] = count;
  request["max_input_tokens"] = 256;
  request["sampling"] = Parse(
      R"({"temperature":0.7,"seed":193,"repeat_penalty":1.1,"presence_penalty":0.1})");
  return request;
}
Value Append(Value left, const Value& right) {
  for (const auto& item : right.items())
    left.push_back(item);
  return left;
}
void CheckPersistentOverwrite(Fixture& fixture) {
  const auto runner = fixture.Runner();
  for (const std::size_t count : {1U, 4U, 17U}) {
    auto state = runner->CreateState();
    std::vector<gufo::server::TextRunnerToken> tokens(count);
    for (std::size_t i = 0; i < count; ++i)
      tokens[i] = static_cast<gufo::server::TextRunnerToken>(3 + i);
    std::size_t offset = 0;
    while (offset < count) {
      const auto step = runner->Prefill(*state, tokens, offset, count - offset);
      Check(step.consumed_tokens > 0, "snapshot fixture made no progress");
      offset += step.consumed_tokens;
    }
    const auto snapshot = runner->SnapshotForPersistence(*state);
    const auto bytes = runner->PersistentSnapshotPayloadBytes(*snapshot);
    std::vector<std::uint8_t> zero(bytes, 0), dirty(bytes, 0xa5);
    Check(runner->SerializePersistentSnapshot(*snapshot, zero) == bytes,
          "zeroed snapshot serialization length");
    Check(runner->SerializePersistentSnapshot(*snapshot, dirty) == bytes,
          "dirty snapshot serialization length");
    Check(zero == dirty, "persistent snapshot retained destination bytes");
  }
}
}  // namespace
int main() {
  const auto path = std::filesystem::temp_directory_path() /
                    ("cointos-gufo-hip-" + std::to_string(getpid()));
  try {
    Fixture fixture;
    CheckPersistentOverwrite(fixture);
    Value saved_tokens, expected;
    {
      cointos::Control control(fixture.Runner(), 2, path, "seeded-hip-qwen");
      const auto prompt = Parse("[3,5,7,9]");
      auto prefill = Step(0, prompt, 0, 1);
      prefill["op"] = "prefill";
      Check(control.Call(prefill).member_size("held") == 4,
            "native prefill position");
      control.Call(Parse(R"({"op":"save","lane":0,"name":"prefilled"})"));
      const auto first = control.Call(Step(0, prompt, 4, 4));
      Check(first.find("tokens")->size() == 4,
            "fixture reached EOS before continuation check");
      saved_tokens = Append(prompt, *first.find("tokens"));
      control.Call(Parse(R"({"op":"save","lane":0,"name":"generated"})"));
      // Interleave a second physical state before continuing the first.
      control.Call(Step(1, Parse("[19,23,29]"), 0, 3));
      expected = control.Call(Step(0, saved_tokens, saved_tokens.size(), 8));
      Check(expected.find("tokens")->size() == 8,
            "fixture ended before its replay check");
      control.Call(Parse(R"({"op":"restore","lane":1,"name":"generated"})"));
      auto forked = control.Call(Step(1, saved_tokens, saved_tokens.size(), 8));
      Check(forked.find("tokens")->dump() == expected.find("tokens")->dump(),
            "HIP snapshot fork changed sampled continuation");
      control.Call(Parse(R"({"op":"restore","lane":0,"name":"prefilled"})"));
      const auto repeated = control.Call(Step(0, prompt, 4, 4));
      Check(repeated.find("tokens")->dump() == first.find("tokens")->dump(),
            "HIP prefill snapshot changed the first draw");
    }
    // A new runner/executor pool must consume only the persisted native state.
    {
      cointos::Control restarted(fixture.Runner(), 2, path, "seeded-hip-qwen");
      restarted.Call(Parse(R"({"op":"restore","lane":0,"name":"generated"})"));
      const auto replayed =
          restarted.Call(Step(0, saved_tokens, saved_tokens.size(), 8));
      Check(replayed.find("tokens")->dump() == expected.find("tokens")->dump(),
            "new HIP runner changed persisted continuation");
    }
    std::filesystem::remove_all(path);
    std::cout << "native HIP Qwen prefill, sampling, lane fork and disk "
                 "continuation passed\n";
    return 0;
  } catch (const std::exception& error) {
    std::filesystem::remove_all(path);
    std::cerr << error.what() << '\n';
    return 1;
  }
}
