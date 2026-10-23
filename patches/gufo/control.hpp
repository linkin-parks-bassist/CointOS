#pragma once

#include <filesystem>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "src/cli/serve/text_model_runner.hpp"
#include "src/core/json.hpp"

namespace cointos {
class Control {
public:
  Control(std::shared_ptr<const gufo::server::TextModelRunner> runner,
          std::size_t lanes, std::filesystem::path snapshots,
          std::string identity);
  gufo::json::Value Call(const gufo::json::Value& request);
  static bool IsMetadata(std::string_view op) {
    return op == "info" || op == "render" || op == "tokenize" || op == "text";
  }
  // CPU-only operations use immutable tokenizer/template data, never lane state.
  gufo::json::Value Metadata(const gufo::json::Value& request) const;

private:
  using Token = gufo::server::TextRunnerToken;
  struct Lane {
    std::unique_ptr<gufo::server::TextRunnerState> state;
    std::vector<Token> tokens;
    std::optional<gufo::sampling::SamplerState> sampler;
    gufo::json::Value sampling;
    std::size_t prompt_size = 0;
  };
  std::shared_ptr<const gufo::server::TextModelRunner> runner_;
  std::vector<Lane> lanes_;
  std::filesystem::path snapshots_;
  std::string identity_;
  gufo::json::Value Render(const gufo::json::Value& request) const;
  void Prefill(Lane& lane, const gufo::json::Value& request);
  gufo::json::Value Save(Lane& lane, const std::string& name);
  gufo::json::Value Restore(Lane& lane, const std::string& name);
};
std::string FileSha256(const std::filesystem::path& path);
}  // namespace cointos
