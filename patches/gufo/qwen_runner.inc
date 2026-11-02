// CointOS persistent control runner, retained from Gufo 1f970923.
// Uses current Gufo kernels; preserves existing on-disk snapshots and resident state.
namespace cointos_control {
constexpr std::array<std::uint8_t, 8> kQwenPersistentSnapshotMagic = {
    'G', 'Q', 'W', 'R', 'U', 'N', '0', '1'};
constexpr std::uint32_t kQwenPersistentPayloadVersion = 3;
constexpr std::size_t kQwenMaxResumeTokens = 9;
constexpr std::size_t kQwenPersistentSnapshotHeaderBytes = 112;
constexpr std::uint32_t kQwenPersistentSpeculativeFlag = 1U << 0U;
constexpr std::uint32_t kQwenPersistentPendingTokenFlag = 1U << 1U;

constexpr std::string_view QwenStateAbi(bool speculative,
                                        bool fp16_attention_kv,
                                        bool bf16_recurrent_state) noexcept {
  if (bf16_recurrent_state) {
    if (speculative) {
      return fp16_attention_kv
                 ? "qwen-gfx1151-dflash-state-v4-fp16-kv-bf16-recurrent"
                 : "qwen-gfx1151-dflash-state-v4-fp32-kv-bf16-recurrent";
    }
    return fp16_attention_kv ? "qwen-gfx1151-state-v3-fp16-kv-bf16-recurrent"
                             : "qwen-gfx1151-state-v3-fp32-kv-bf16-recurrent";
  }
  if (speculative) {
    return fp16_attention_kv ? "qwen-gfx1151-dflash-state-v3-fp16-kv"
                             : "qwen-gfx1151-dflash-state-v3-fp32-kv";
  }
  return fp16_attention_kv ? "qwen-gfx1151-state-v2-fp16-kv"
                           : "qwen-gfx1151-state-v2-fp32-kv";
}

std::vector<std::uint8_t> QwenCompatibilityIdentity(
    std::string_view artifact_fingerprint,
    std::string_view draft_artifact_fingerprint, std::uint32_t max_context,
    const hip::QwenExecutionPolicy& execution_policy, bool speculative,
    const speculative::SpeculativeOptions& speculative_options) {
  if (!IsSha256Hex(artifact_fingerprint)) {
    throw std::invalid_argument(
        "Qwen disk cache requires an artifact fingerprint");
  }
  if (speculative && !IsSha256Hex(draft_artifact_fingerprint)) {
    throw std::invalid_argument(
        "Qwen DFlash disk cache requires a draft artifact fingerprint");
  }
  const std::string_view state_abi =
      QwenStateAbi(speculative, execution_policy.UsesFp16AttentionKv(),
                   execution_policy.UsesBf16RecurrentState());
  std::ostringstream identity;
  identity << "schema=gufo-text-continuation-v2\n"
           << "model_kind=qwen3.8\n"
           << "artifact_id=" << core::kGgufIdentityScheme << ':'
           << artifact_fingerprint << '\n'
           << "tokenizer=embedded-in-artifact\n"
           << "chat_template=qwen38-reasoning-compiled-v3\n"
           << "chat_template_reference_sha256="
           << tokenization::QwenChatTemplate::OfficialTemplateSha256() << '\n'
           << "state_abi=" << state_abi << '\n'
           << "payload_layout=qwen-gfx1151-live-prefix-v3\n"
           // Older learned boundaries could keep logits from an earlier
           // prefix. Their payload has no readiness tag to distinguish them.
           << "checkpoint_frontier=complete-prefix-v1\n"
           << "numerics=qwen-bf16-fp32-prefill-v1\n"
           << "rmsnorm=fused-square-sum-v1\n"
           << "prefill_attention=visible-causal-tail-v1\n"
           << "attention_split_min_context="
           << hip::detail::kSplitKDecodeAttentionMinContext << '\n'
           << "attention_split_count="
           << hip::detail::kSplitKDecodeAttentionMaxSplits << '\n'
           << "kv_storage="
           << (execution_policy.UsesFp16AttentionKv() ? "fp16" : "fp32") << '\n'
           << "recurrent_storage="
           << (execution_policy.UsesBf16RecurrentState() ? "bf16" : "fp32")
           << '\n'
           << "context_tokens=" << max_context << '\n'
           << "position_policy=absolute-v1\n"
           << "rope_window_policy=qwen-gguf-config-v1\n"
           << "adapters=none\n";
  if (speculative) {
    identity
        << "draft_backend=dflash2-gfx1151-v1\n"
        << "draft_artifact_id=" << core::kGgufIdentityScheme << ':'
        << draft_artifact_fingerprint << '\n'
        << "draft_state_layout=dflash-window-kv-and-frontier-v4\n"
        << "draft_policy="
        << speculative::DFlashDraftPolicyName(speculative_options.dflash_policy)
        << "-v3\n"
        << "draft_max_tokens=" << speculative_options.max_draft_tokens << '\n'
        << "draft_min_tokens=" << speculative_options.min_draft_tokens << '\n'
        << "draft_initial_tokens=" << speculative_options.initial_draft_tokens
        << '\n'
        << "draft_rolling_window=" << speculative_options.rolling_window << '\n'
        << std::setprecision(std::numeric_limits<float>::max_digits10)
        << "draft_target_acceptance="
        << speculative_options.target_acceptance_rate << '\n'
        << "draft_adaptive="
        << (speculative_options.enable_adaptive_draft_length ? "true" : "false")
        << '\n'
        << "draft_batched_verification="
        << (speculative_options.use_batched_verification ? "true" : "false")
        << '\n'
        << "draft_target_verification=decode-equivalent-v1\n";
  }
  const std::string canonical = identity.str();
  return {canonical.begin(), canonical.end()};
}

template<typename T>
  requires(std::is_unsigned_v<T>)
void PutLittleEndian(std::span<std::uint8_t> destination, std::size_t offset,
                     T value) {
  if (offset > destination.size() || sizeof(T) > destination.size() - offset) {
    throw std::length_error("Qwen persistent snapshot header is truncated");
  }
  for (std::size_t byte = 0; byte < sizeof(T); ++byte) {
    destination[offset + byte] =
        static_cast<std::uint8_t>(value >> (byte * 8U));
  }
}

template<typename T>
  requires(std::is_unsigned_v<T>)
T GetLittleEndian(std::span<const std::uint8_t> source, std::size_t offset) {
  if (offset > source.size() || sizeof(T) > source.size() - offset) {
    throw std::invalid_argument("Qwen persistent snapshot header is truncated");
  }
  T value = 0;
  for (std::size_t byte = 0; byte < sizeof(T); ++byte) {
    value |= static_cast<T>(source[offset + byte]) << (byte * 8U);
  }
  return value;
}

std::size_t CheckedPersistentAdd(std::size_t left, std::size_t right) {
  if (right > std::numeric_limits<std::size_t>::max() - left) {
    throw std::overflow_error("Qwen persistent snapshot size overflows");
  }
  return left + right;
}

std::size_t PersistentSizeFromU64(std::uint64_t value) {
  if (value > std::numeric_limits<std::size_t>::max()) {
    throw std::overflow_error("Qwen persistent snapshot size overflows");
  }
  return static_cast<std::size_t>(value);
}

class QwenTextRunnerState final : public TextRunnerState {
public:
  QwenTextRunnerState(
      std::shared_ptr<const hip::QwenGpuModel> model, std::uint32_t max_context,
      std::shared_ptr<const hip::QwenDFlashGpuModel> dflash_model,
      speculative::SpeculativeOptions speculative_options,
      hip::QwenExecutionPolicy execution_policy)
      : model_(std::move(model)) {
    resume_tokens_.reserve(kQwenMaxResumeTokens);
    rollback_tokens_.reserve(kQwenMaxResumeTokens);
    std::string error;
    executor_ = hip::QwenGpuExecutor::Create(model_, &error, max_context,
                                             execution_policy);
    if (executor_ == nullptr) {
      throw std::runtime_error("Failed to create GPU session: " + error);
    }
    if (dflash_model != nullptr) {
      auto draft_backend = hip::QwenDFlashGpuDraftBackend::Create(
          std::move(dflash_model),
          hip::QwenDFlashGpuDraftConfig{
              .max_context = max_context,
              .max_draft_tokens = speculative_options.max_draft_tokens,
              .policy = speculative_options.dflash_policy,
          },
          &error);
      if (draft_backend == nullptr) {
        throw std::runtime_error("Failed to create DFlash session: " + error);
      }
      draft_backend_ = draft_backend.get();
      verifier_ = std::make_unique<speculative::SpeculativeVerifier>(
          *executor_, std::move(draft_backend), speculative_options);
    }
  }

  void SetCancellationCheck(const CancellationCheck& check) override {
    executor_->SetCancellationCheck(check);
  }

  void Invalidate() noexcept override {
    if (verifier_ != nullptr) {
      verifier_->Reset();
    }
    executor_->Reset();
    sequence_.clear();
    position_ = 0;
    frontier_.reset();
    frontier_logits_.clear();
    frontier_published_ = false;
    resume_tokens_.clear();
    rollback_position_.reset();
    rollback_tokens_.clear();
    rollback_logits_.clear();
  }

  [[nodiscard]] TextRunnerMeasuredResources MeasuredResources()
      const noexcept override {
    try {
      auto usage = executor_->GetMemoryUsage();
      if (draft_backend_ != nullptr) {
        const auto draft = draft_backend_->GetMemoryUsage();
        usage.request_state_bytes += draft.request_state_bytes;
        usage.temporary_scratch_bytes += draft.temporary_scratch_bytes;
      }
      return {
          .per_request_state_bytes = usage.request_state_bytes,
          .temporary_scratch_bytes = usage.temporary_scratch_bytes,
      };
    } catch (...) {
      return {};
    }
  }

  [[nodiscard]] bool speculative() const noexcept {
    return verifier_ != nullptr;
  }

  void PrimeSpeculative(std::span<const TextRunnerToken> prompt,
                        bool decode_ready) {
    if (verifier_ == nullptr) {
      throw std::logic_error("Qwen state has no speculative verifier");
    }
    frontier_ = verifier_->Prime(prompt, decode_ready);
    frontier_logits_.clear();
    if (decode_ready) {
      const auto logits = verifier_->CopyLastTargetLogits();
      frontier_logits_.assign(logits.begin(), logits.end());
    }
    sequence_.assign(prompt.begin(), prompt.end());
    position_ = prompt.size();
    frontier_published_ = false;
    resume_tokens_.clear();
    rollback_position_.reset();
  }

  void PrepareContinuation(std::span<const TextRunnerToken> prefix) {
    if (position_ != prefix.size() || !frontier_.has_value()) {
      throw std::logic_error(
          "Qwen retained prefix does not match its target state");
    }
    if (verifier_ != nullptr) {
      sequence_.assign(prefix.begin(), prefix.end());
    }
    frontier_published_ = false;
    rollback_position_.reset();
  }

  void PreparePrefixReuse(std::span<const TextRunnerToken> prefix) {
    PrepareContinuation(prefix);
    if (verifier_ != nullptr) {
      verifier_->BeginRequest();
      // Verification's frontier may be a sampled draw. A new request must
      // select from its distribution again, including when it switches to
      // greedy sampling or omits the previously published pending token.
      if (!resume_tokens_.empty() && !frontier_logits_.empty()) {
        sampling::SamplerState greedy;
        frontier_ = greedy.Sample(frontier_logits_);
      }
    }
  }

  bool ResumeGeneratedToken(TextRunnerToken token, bool decode_ready) {
    if (resume_tokens_.empty())
      return false;
    if (resume_tokens_.front() != token) {
      resume_tokens_.clear();
      return false;
    }
    if (verifier_ != nullptr && sequence_.size() != position_ &&
        (sequence_.size() != position_ + 1 || sequence_.back() != token)) {
      throw std::logic_error(
          "Qwen pending token does not match its retained sequence");
    }
    resume_tokens_.erase(resume_tokens_.begin());
    // This token was already published by the previous request. Consume it
    // with decode arithmetic, exactly as AR did, before chunking the new
    // prompt suffix. Including it in a prefill chunk changes recurrent state.
    const auto position = static_cast<std::uint32_t>(position_);
    frontier_ = verifier_ != nullptr
                    ? verifier_->AdvanceCommittedToken(token, position)
                    : executor_->ForwardToken(token, position);
    if (verifier_ != nullptr) {
      // A continuing decode already published this token in sequence_. A
      // restored/new-request prefix may end at the physical position instead.
      // In both cases consume it exactly once in the logical token index.
      sequence_.resize(position_);
      sequence_.push_back(token);
    }
    ++position_;
    frontier_logits_.clear();
    if (decode_ready) {
      const auto logits = executor_->CopyLastLogits();
      frontier_logits_.assign(logits.begin(), logits.end());
    }
    // Consuming the published token creates a fresh, unpublished frontier.
    // This is a decode boundary, not a new request/policy reset.
    frontier_published_ = false;
    rollback_position_.reset();
    return true;
  }

  void ExtendSpeculative(std::span<const TextRunnerToken> suffix,
                         bool decode_ready) {
    if (verifier_ == nullptr || !frontier_.has_value()) {
      throw std::logic_error("Qwen speculative prefix is not initialized");
    }
    if (sequence_.size() != position_) {
      throw std::logic_error(
          "Qwen speculative sequence does not match retained position");
    }
    frontier_ = verifier_->ExtendPrompt(
        suffix, static_cast<std::uint32_t>(position_), decode_ready);
    sequence_.insert(sequence_.end(), suffix.begin(), suffix.end());
    position_ += suffix.size();
    frontier_logits_.clear();
    if (decode_ready) {
      const auto logits = verifier_->CopyLastTargetLogits();
      frontier_logits_.assign(logits.begin(), logits.end());
    }
    frontier_published_ = false;
  }

  [[nodiscard]] TextRunnerToken SelectFrontier(
      sampling::SamplerState& sampler) const {
    if (!frontier_.has_value()) {
      throw std::logic_error("Qwen state has no next-token frontier");
    }
    if (sampler.config().can_use_unmodified_argmax() ||
        (verifier_ == nullptr && sampler.CanSelectArgmax(*frontier_))) {
      return *frontier_;
    }
    if (frontier_logits_.empty()) {
      return executor_->SampleLastLogits(sampler);
    }
    return executor_->SampleCachedLogits(frontier_logits_, sampler);
  }

  [[nodiscard]] bool PrepareSpeculativeDecode(std::size_t max_tokens,
                                              sampling::SamplerState& sampler,
                                              TextDecodeStep& result) {
    if (verifier_ == nullptr || !frontier_.has_value()) {
      throw std::logic_error("Qwen speculative state has no frontier");
    }
    if (max_tokens == 0) {
      throw std::invalid_argument(
          "Qwen speculative decode budget must be at least one token");
    }
    resume_tokens_.clear();
    if (!frontier_published_) {
      if (!sampler.config().can_use_unmodified_argmax())
        frontier_ = SelectFrontier(sampler);
      if (!AppendSpeculativeSelection(*frontier_, sampler, result))
        return false;
      frontier_published_ = true;
    }
    return result.selections.size() < max_tokens;
  }

  [[nodiscard]] speculative::SpeculativeVerifier::StepRequest
  VerificationRequest(std::size_t remaining, sampling::SamplerState& sampler) {
    rollback_position_ = position_;
    rollback_tokens_.assign(1, *frontier_);
    rollback_logits_ = std::move(frontier_logits_);
    // Verification keeps its own EOS handling: the tokenizer stop set already
    // covers EOS, so a sentinel id here would change nothing. An ignore-EOS
    // request instead publishes the stop token in AppendSpeculativeSelection
    // and continues, at the cost of a window clipped on every EOS crossing.
    return {*verifier_,
            sequence_,
            static_cast<std::uint32_t>(position_),
            *frontier_,
            model_->GetTokenizer().GetEosTokenId(),
            static_cast<std::uint32_t>(std::min<std::size_t>(
                remaining, std::numeric_limits<std::uint32_t>::max())),
            sampler};
  }

  void FinishSpeculativeDecode(
      speculative::SpeculativeVerifier::StepResult verification,
      sampling::SamplerState& sampler, TextDecodeStep& result) {
    result.draft_rounds = verification.draft_count > 0 ? 1 : 0;
    result.draft_tokens = verification.draft_count;
    result.draft_accepted_tokens = verification.accepted_count;
    result.execution_plan = {
        .kind = verification.physical_width > 1
                    ? TextExecutionPlanKind::kBatched
                    : TextExecutionPlanKind::kSerial,
        .physical_width = verification.physical_width,
    };
    for (const TextRunnerToken token : verification.emitted_tokens) {
      // Each prediction consumes one input, including a terminal prediction.
      // EOS itself remains the unconsumed frontier and is not published.
      ++position_;
      if (!AppendSpeculativeSelection(token, sampler, result))
        break;
      rollback_tokens_.push_back(token);
    }
    frontier_ = verification.next_token;
    frontier_logits_ = std::move(verification.next_token_logits);
    frontier_published_ = !result.stop;
    set_pending_token(frontier_published_ ? frontier_ : std::nullopt);
    if (verification.draft_count == 0)
      rollback_position_.reset();
  }

  void PrepareCancellation() {
    if (!rollback_position_)
      return;
    if (rollback_tokens_.empty() ||
        rollback_tokens_.size() > kQwenMaxResumeTokens ||
        rollback_logits_.empty())
      throw std::logic_error(
          "Qwen cancelled verification has no exact frontier");
    // Verification already saved the target state. Its target features are
    // still pending in the draft, so rewinding needs no new per-step copy.
    draft_backend_->DiscardPendingTargetContext(
        static_cast<std::uint32_t>(*rollback_position_));
    executor_->RestoreState();
    position_ = *rollback_position_;
    sequence_.resize(position_);
    frontier_logits_ = std::move(rollback_logits_);
    sampling::SamplerState greedy;
    frontier_ = greedy.Sample(frontier_logits_);
    frontier_published_ = false;
    resume_tokens_ = std::move(rollback_tokens_);
    rollback_position_.reset();
  }

  [[nodiscard]] TextDecodeStep DecodeSpeculative(
      std::size_t max_tokens, sampling::SamplerState& sampler) {
    TextDecodeStep result;
    sampling::SamplerState working_sampler = sampler;
    if (PrepareSpeculativeDecode(max_tokens, working_sampler, result)) {
      const auto request = VerificationRequest(
          max_tokens - result.selections.size(), working_sampler);
      auto verification = verifier_->VerifyStep(
          sequence_, request.position, request.current_token, request.eos_id,
          request.max_emitted_tokens, working_sampler);
      FinishSpeculativeDecode(std::move(verification), working_sampler, result);
    }
    sampler.SetRngState(working_sampler.rng_state());
    return result;
  }

  [[nodiscard]] hip::QwenGpuExecutor& executor() const { return *executor_; }
  [[nodiscard]] std::size_t position() const noexcept { return position_; }
  void set_position(std::size_t position) noexcept { position_ = position; }
  [[nodiscard]] const std::optional<TextRunnerToken>& frontier()
      const noexcept {
    return frontier_;
  }
  void set_frontier(TextRunnerToken frontier) noexcept {
    frontier_ = frontier;
    frontier_logits_.clear();
    frontier_published_ = false;
    resume_tokens_.clear();
  }
  [[nodiscard]] std::vector<float> CopyFrontierLogits() const {
    if (!frontier_logits_.empty()) {
      return frontier_logits_;
    }
    const auto logits = executor_->CopyLastLogits();
    return {logits.begin(), logits.end()};
  }
  void RestoreFrontierLogits(std::vector<float> logits) {
    frontier_logits_ = std::move(logits);
  }
  [[nodiscard]] const std::vector<TextRunnerToken>& pending_tokens()
      const noexcept {
    return resume_tokens_;
  }
  void set_pending_token(std::optional<TextRunnerToken> token) {
    resume_tokens_.clear();
    if (token)
      resume_tokens_.push_back(*token);
  }
  void RestorePendingTokens(std::span<const TextRunnerToken> tokens) {
    resume_tokens_.assign(tokens.begin(), tokens.end());
    rollback_position_.reset();
  }
  [[nodiscard]] std::unique_ptr<speculative::SpeculativeVerifierSnapshot>
  SaveVerifierSnapshot() const {
    return verifier_ != nullptr ? verifier_->Snapshot() : nullptr;
  }
  [[nodiscard]] std::size_t SnapshotPayloadBytes() const {
    std::size_t bytes = executor_->SnapshotPayloadBytes(position_);
    const auto checked_add = [&bytes](std::size_t value) {
      if (value > std::numeric_limits<std::size_t>::max() - bytes) {
        throw std::overflow_error("Qwen snapshot size overflows");
      }
      bytes += value;
    };
    const std::size_t logits_count = frontier_logits_.empty()
                                         ? model_->GetConfig().vocab_size
                                         : frontier_logits_.size();
    if (logits_count >
        std::numeric_limits<std::size_t>::max() / sizeof(float)) {
      throw std::overflow_error("Qwen snapshot size overflows");
    }
    checked_add(logits_count * sizeof(float));
    checked_add(resume_tokens_.size() * sizeof(TextRunnerToken));
    checked_add(std::ranges::count_if(executor_->VisionLayout().images,
                                      [this](const auto& image) {
                                        return image.offset < position_;
                                      }) *
                sizeof(models::qwen::vision::ImageGrid));
    if (verifier_ != nullptr) {
      checked_add(verifier_->SnapshotPayloadBytes());
    }
    return bytes;
  }
  void RestoreVerifierSnapshot(
      const speculative::SpeculativeVerifierSnapshot& snapshot) {
    if (verifier_ == nullptr) {
      throw std::invalid_argument(
          "cannot restore speculative state into a plain Qwen session");
    }
    verifier_->RestoreSnapshot(snapshot);
  }
  void RestoreVerifierPersistentSnapshot(
      std::span<const std::uint8_t> payload) {
    if (verifier_ == nullptr) {
      throw std::invalid_argument(
          "cannot restore speculative persistent state into a plain Qwen "
          "session");
    }
    verifier_->RestorePersistentSnapshot(payload);
  }

private:
  bool AppendSpeculativeSelection(TextRunnerToken token,
                                  sampling::SamplerState& sampler,
                                  TextDecodeStep& result) {
    if (stop_at_eos() && model_->GetTokenizer().IsStopToken(token)) {
      result.stop = true;
      return false;
    }
    result.selections.push_back({
        .stop = false,
        .token = token,
        .piece = std::string(model_->GetTokenizer().DecodeToken(token)),
    });
    sequence_.push_back(token);
    set_pending_token(token);
    sampler.Accept(token);
    return true;
  }

  std::shared_ptr<const hip::QwenGpuModel> model_;
  std::unique_ptr<hip::QwenGpuExecutor> executor_;
  std::unique_ptr<speculative::SpeculativeVerifier> verifier_;
  // Owned by verifier_; used only to account the session's draft allocations.
  hip::QwenDFlashGpuDraftBackend* draft_backend_{nullptr};
  std::vector<TextRunnerToken> sequence_;
  std::size_t position_{0};
  std::optional<TextRunnerToken> frontier_;
  std::vector<float> frontier_logits_;
  bool frontier_published_{false};
  std::vector<TextRunnerToken> resume_tokens_;
  std::optional<std::size_t> rollback_position_;
  std::vector<TextRunnerToken> rollback_tokens_;
  std::vector<float> rollback_logits_;
};

class QwenTextRunnerSnapshot final : public TextRunnerSnapshot {
public:
  QwenTextRunnerSnapshot(
      std::shared_ptr<const hip::QwenGpuModel> model,
      std::unique_ptr<hip::QwenGpuSnapshot> snapshot, std::size_t position,
      std::optional<TextRunnerToken> frontier,
      std::vector<float> frontier_logits,
      std::vector<TextRunnerToken> pending_tokens,
      std::unique_ptr<speculative::SpeculativeVerifierSnapshot>
          verifier_snapshot)
      : model(std::move(model)),
        snapshot(std::move(snapshot)),
        position(position),
        frontier(frontier),
        frontier_logits(std::move(frontier_logits)),
        pending_tokens(std::move(pending_tokens)),
        verifier_snapshot(std::move(verifier_snapshot)) {}

  [[nodiscard]] std::size_t PayloadBytes() const noexcept override {
    return (snapshot != nullptr ? snapshot->PayloadBytes() : 0) +
           frontier_logits.size() * sizeof(float) +
           pending_tokens.size() * sizeof(TextRunnerToken) +
           (verifier_snapshot != nullptr ? verifier_snapshot->PayloadBytes()
                                         : 0);
  }

  std::shared_ptr<const hip::QwenGpuModel> model;
  std::unique_ptr<hip::QwenGpuSnapshot> snapshot;
  std::size_t position;
  std::optional<TextRunnerToken> frontier;
  std::vector<float> frontier_logits;
  std::vector<TextRunnerToken> pending_tokens;
  std::unique_ptr<speculative::SpeculativeVerifierSnapshot> verifier_snapshot;
};

QwenTextRunnerState& RequireQwenState(TextRunnerState& state) {
  auto* qwen = dynamic_cast<QwenTextRunnerState*>(&state);
  if (qwen == nullptr) {
    throw std::logic_error("text runner state is not Qwen");
  }
  return *qwen;
}

const QwenTextRunnerState& RequireQwenState(const TextRunnerState& state) {
  const auto* qwen = dynamic_cast<const QwenTextRunnerState*>(&state);
  if (qwen == nullptr) {
    throw std::logic_error("text runner state is not Qwen");
  }
  return *qwen;
}

// Owns a four-byte device buffer and a private stream from load, so probing
// a lost context needs no allocation. HIP context loss is sticky: after a GPU
// reset even this memset fails with a hard error. Only such an error marks the
// device lost; a memset still pending at the deadline may be queued behind
// long kernels on the shared hardware queues, so it counts as usable.
class QwenTextRunner final : public HipTextModelRunner {
public:
  sampling::JsonConstraint::ToolFormat ToolFormat() const override {
    return sampling::JsonConstraint::ToolFormat::kQwen;
  }
  QwenTextRunner(
      std::shared_ptr<const hip::QwenGpuModel> model, std::uint32_t max_context,
      std::shared_ptr<const hip::QwenDFlashGpuModel> dflash_model = nullptr,
      speculative::SpeculativeOptions speculative_options = {},
      std::string artifact_fingerprint = {},
      std::string draft_artifact_fingerprint = {})
      : model_(std::move(model)),
        dflash_model_(std::move(dflash_model)),
        max_context_(max_context),
        speculative_options_(speculative_options),
        execution_policy_(hip::QwenExecutionPolicy::Production()) {
    if (!artifact_fingerprint.empty()) {
      const bool speculative = dflash_model_ != nullptr;
      persistence_ = TextRunnerPersistenceDescriptor{
          .compatibility_identity = QwenCompatibilityIdentity(
              artifact_fingerprint, draft_artifact_fingerprint, max_context_,
              execution_policy_, speculative, speculative_options_),
          .payload_version = kQwenPersistentPayloadVersion,
      };
    }
  }

  [[nodiscard]] TextRunnerDescriptor Descriptor() const override {
    const bool speculative_enabled = dflash_model_ != nullptr;
    return {
        .model_id = model_->GetConfig().model_name,
        .state_abi = std::string(QwenStateAbi(
            speculative_enabled, execution_policy_.UsesFp16AttentionKv(),
            execution_policy_.UsesBf16RecurrentState())),
        .max_context = max_context_,
        .capabilities =
            TextRunnerCapabilities{
                .incremental_prefill = true,
                .snapshot = true,
                .fork = true,
                .final_token_advance_required = !speculative_enabled,
                .incremental_text_is_exact = true,
                .multi_token_decode = speculative_enabled,
                .batched_multi_token_decode =
                    speculative_enabled && MaximumDecodeBatchWidth() > 1,
                .batched_multi_token_decode_max_width =
                    speculative_enabled ? MaximumDecodeBatchWidth() : 0,
                .prefix_reuse = true,
            },
        .persistence = persistence_,
    };
  }

  [[nodiscard]] TextRunnerResourceClaim ResourceClaim() const override {
    auto usage = hip::QwenGpuExecutor::EstimateMemoryUsage(
        model_->GetConfig(), max_context_, execution_policy_);
    std::size_t resident_weights = model_->GetResidentBytes();
    if (dflash_model_ != nullptr) {
      const auto draft = hip::QwenDFlashGpuExecutor::EstimateMemoryUsage(
          *dflash_model_, max_context_, MaximumDecodeBatchWidth());
      usage.request_state_bytes += draft.request_state_bytes;
      usage.temporary_scratch_bytes += draft.temporary_scratch_bytes;
      resident_weights += dflash_model_->GetPackedWeightBytes();
    }
    std::size_t free_bytes = 0;
    std::size_t total_bytes = 0;
    std::optional<std::size_t> capacity;
    if (hipMemGetInfo(&free_bytes, &total_bytes) == hipSuccess) {
      capacity = free_bytes;
    }
    // Snapshot buffers are device allocations, but on a unified-memory APU
    // they are carved from the same RAM as every host allocation, and HIP's
    // free figure does not see host pressure. Cap them by the host budget too.
    std::size_t snapshot_capacity = HostSnapshotBudgetBytes();
    std::size_t snapshot_ceiling = HostSnapshotCeilingBytes();
    if (capacity.has_value()) {
      snapshot_capacity = std::min(snapshot_capacity, *capacity);
      snapshot_ceiling = std::min(snapshot_ceiling, *capacity);
    }
    return {
        .resident_weights_bytes = resident_weights,
        .state_capacity_bytes = capacity,
        .per_request_state_bytes = usage.request_state_bytes,
        .temporary_scratch_bytes = usage.temporary_scratch_bytes,
        .retained_snapshot_capacity_bytes = snapshot_capacity,
        .retained_snapshot_ceiling_bytes = snapshot_ceiling,
        .requires_device_runtime_lock = true,
    };
  }

  [[nodiscard]] std::vector<TextExecutionPlan> SupportedPlans() const override {
    std::vector<TextExecutionPlan> plans{
        {
            .kind = TextExecutionPlanKind::kSerial,
            .physical_width = 1,
        },
    };
    // Report actual session widths, including C6. Speculation reserves up to
    // eight token rows per session in the coordinator's existing scratch.
    for (std::size_t width = 2; width <= MaximumDecodeBatchWidth(); ++width) {
      plans.push_back({
          .kind = TextExecutionPlanKind::kBatched,
          .physical_width = width,
      });
    }
    return plans;
  }

  [[nodiscard]] std::shared_ptr<const sampling::ConstraintVocabulary>
  BuildConstraintVocabulary() const override {
    return std::make_shared<const sampling::ConstraintVocabulary>(
        model_->GetTokenizer().GetVocabSize(), [this](std::uint32_t id) {
          const auto& tokenizer = model_->GetTokenizer();
          return sampling::ConstraintVocabulary::Piece{
              tokenizer.DecodeTokenCopy(id), tokenizer.IsStopToken(id)};
        });
  }

  [[nodiscard]] std::vector<TextRunnerToken> Tokenize(
      std::string_view text) const override {
    return model_->GetTokenizer().Encode(text);
  }

  [[nodiscard]] std::optional<std::vector<TextRunnerToken>> RenderAndTokenize(
      const ChatRequest& request) const override {
    return tokenization::QwenChatTemplate::RenderAndTokenize(
        model_->GetTokenizer(), request.messages,
        request.tool_choice == ChatRequest::ToolChoice::kNone
            ? std::span<const tokenization::ChatTool>{}
            : std::span<const tokenization::ChatTool>{request.tools},
        QwenChatOptions(request, max_context_));
  }

  [[nodiscard]] std::optional<TextPreparedPrompt> PreparePrompt(
      const ChatRequest& request) const override {
    return PrepareQwenPrompt(request, model_->GetTokenizer(),
                             model_->VisionEncoder(), max_context_, image_cache_);
  }

  [[nodiscard]] std::optional<std::size_t> CountPromptTokens(
      const ChatRequest& request) const override {
    return CountQwenPromptTokens(request, model_->GetTokenizer(),
                                 model_->VisionEncoder(), max_context_, image_cache_);
  }

  void SetPromptContext(
      TextRunnerState& state,
      std::shared_ptr<const TextPromptContext> context) const override {
    RequireQwenState(state).executor().ConfigureVision(QwenPrompt(context),
                                                       model_->VisionEncoder());
  }

  [[nodiscard]] TextGenerationBackend::InitialOutputState InitialOutputState(
      const ChatRequest& request) const override {
    return QwenChatOptions(request, max_context_).enable_thinking
               ? TextGenerationBackend::InitialOutputState::kReasoning
               : TextGenerationBackend::InitialOutputState::kContent;
  }

  [[nodiscard]] std::string Decode(
      std::span<const TextRunnerToken> tokens) const override {
    return model_->GetTokenizer().Decode(tokens);
  }

  [[nodiscard]] std::unique_ptr<TextRunnerState> CreateState() const override {
    return std::make_unique<QwenTextRunnerState>(
        model_, max_context_, dflash_model_, speculative_options_,
        execution_policy_);
  }

  void PreparePrefixReuse(
      TextRunnerState& state,
      std::span<const TextRunnerToken> prefix) const override {
    auto& qwen = RequireQwenState(state);
    qwen.PreparePrefixReuse(prefix);
  }

  void PrepareContinuation(
      TextRunnerState& state,
      std::span<const TextRunnerToken> prefix) const override {
    RequireQwenState(state).PrepareContinuation(prefix);
  }

  [[nodiscard]] TextPrefillStep Prefill(
      TextRunnerState& state, std::span<const TextRunnerToken> prompt,
      std::size_t offset, std::size_t max_input_tokens) const override {
    auto& qwen = RequireQwenState(state);
    if (offset != qwen.position()) {
      throw std::logic_error(
          "Qwen prefill offset does not match retained state");
    }
    if (offset >= prompt.size()) {
      throw std::logic_error("Qwen prefill has no remaining input");
    }
    max_input_tokens = std::min<std::size_t>(
        max_input_tokens, qwen.executor().GetMaxPromptBatch());
    if (max_input_tokens != 0 && offset != 0 &&
        qwen.ResumeGeneratedToken(prompt[offset],
                                  offset + 1 == prompt.size())) {
      return {.consumed_tokens = 1,
              .decode_ready = offset + 1 == prompt.size()};
    }
    if (qwen.speculative()) {
      if (offset == 0) {
        const auto consumed = std::min(max_input_tokens, prompt.size());
        if (consumed == 0) {
          throw std::logic_error(
              "Qwen prefill requires a nonzero token budget");
        }
        qwen.PrimeSpeculative(prompt.first(consumed),
                              consumed == prompt.size());
        return {.consumed_tokens = consumed,
                .decode_ready = consumed == prompt.size()};
      }
      const std::size_t consumed =
          std::min(max_input_tokens, prompt.size() - offset);
      if (consumed == 0) {
        throw std::logic_error(
            "Qwen DFlash retained prefix has no suffix to prefill");
      }
      qwen.ExtendSpeculative(prompt.subspan(offset, consumed),
                             offset + consumed == prompt.size());
      return {
          .consumed_tokens = consumed,
          .decode_ready = offset + consumed == prompt.size(),
      };
    }

    const std::size_t consumed =
        std::min(max_input_tokens, prompt.size() - offset);
    const bool decode_ready = offset + consumed == prompt.size();
    const auto frontier = qwen.executor().ForwardPromptBatch(
        prompt.subspan(offset, consumed), static_cast<std::uint32_t>(offset),
        decode_ready);
    qwen.set_position(offset + consumed);
    if (decode_ready) {
      qwen.set_frontier(frontier);
    }
    return {
        .consumed_tokens = consumed,
        .decode_ready = decode_ready,
    };
  }

  [[nodiscard]] TextDecodeSelection SelectNext(
      TextRunnerState& state, sampling::SamplerState& sampler) const override {
    auto& qwen = RequireQwenState(state);
    const TextRunnerToken token = qwen.SelectFrontier(sampler);
    if (EndsTurn(qwen, model_->GetTokenizer(), token)) {
      return {
          .stop = true,
          .token = 0,
          .piece = {},
      };
    }
    // Keep the selected token separate from the argmax frontier: sampled
    // cancellation and prompt snapshot restore must not replace that argmax.
    qwen.set_pending_token(token);
    return {
        .stop = false,
        .token = token,
        .piece = std::string(model_->GetTokenizer().DecodeToken(token)),
    };
  }

  void Advance(TextRunnerState& state, TextRunnerToken token) const override {
    auto& qwen = RequireQwenState(state);
    if (qwen.speculative()) {
      throw std::logic_error(
          "Qwen DFlash decoding requires a multi-token decode step");
    }
    if (!qwen.frontier().has_value()) {
      throw std::logic_error("Qwen decode state has no retained frontier");
    }
    const auto frontier = qwen.executor().ForwardToken(
        token, static_cast<std::uint32_t>(qwen.position()));
    qwen.set_position(qwen.position() + 1);
    qwen.set_frontier(frontier);
  }

  [[nodiscard]] std::optional<TextDecodeSelection> PreviewFirstToken(
      TextRunnerState& state, sampling::SamplerState& sampler) const override {
    return SelectNext(state, sampler);
  }

  [[nodiscard]] TextDecodeStep DecodeStep(
      TextRunnerState& state, std::size_t max_tokens,
      sampling::SamplerState& sampler) const override {
    auto& qwen = RequireQwenState(state);
    if (!qwen.speculative()) {
      return TextModelRunner::DecodeStep(state, max_tokens, sampler);
    }
    return qwen.DecodeSpeculative(max_tokens, sampler);
  }

  [[nodiscard]] std::vector<TextDecodeStep> DecodeBatch(
      std::span<const TextRunnerDecode> decodes) const override {
    if (dflash_model_ == nullptr || decodes.size() < 2 ||
        decodes.size() > MaximumDecodeBatchWidth()) {
      return TextModelRunner::DecodeBatch(decodes);
    }
    std::vector<TextDecodeStep> steps(decodes.size());
    std::vector<QwenTextRunnerState*> states;
    std::vector<sampling::SamplerState> samplers;
    std::vector<speculative::SpeculativeVerifier::StepRequest> requests;
    std::vector<std::size_t> indices;
    states.reserve(decodes.size());
    samplers.reserve(decodes.size());
    requests.reserve(decodes.size());
    indices.reserve(decodes.size());
    for (std::size_t index = 0; index < decodes.size(); ++index) {
      const auto& decode = decodes[index];
      auto& state = RequireQwenState(decode.state.get());
      states.push_back(&state);
      auto& sampler = samplers.emplace_back(decode.sampler.get());
      if (state.PrepareSpeculativeDecode(decode.max_tokens, sampler,
                                         steps[index])) {
        requests.push_back(state.VerificationRequest(
            decode.max_tokens - steps[index].selections.size(), sampler));
        indices.push_back(index);
      }
    }
    auto verified = speculative::SpeculativeVerifier::VerifyBatch(requests);
    for (std::size_t item = 0; item < indices.size(); ++item) {
      const std::size_t index = indices[item];
      states[index]->FinishSpeculativeDecode(std::move(verified[item]),
                                             samplers[index], steps[index]);
    }
    for (std::size_t index = 0; index < decodes.size(); ++index)
      decodes[index].sampler.get().SetRngState(samplers[index].rng_state());
    return steps;
  }

  void AdvanceBatch(
      std::span<const TextRunnerAdvance> advances) const override {
    if (dflash_model_ != nullptr) {
      throw std::logic_error(
          "Qwen DFlash sessions do not support batch advance");
    }
    if (advances.size() < 2 || advances.size() > 8) {
      throw std::invalid_argument(
          "Qwen batched decode requires two to eight sessions");
    }

    std::vector<hip::QwenGpuBatchItem> items;
    std::vector<QwenTextRunnerState*> states;
    items.reserve(advances.size());
    states.reserve(advances.size());
    for (const auto& advance : advances) {
      auto& qwen = RequireQwenState(advance.state.get());
      if (!qwen.frontier().has_value()) {
        throw std::logic_error("Qwen batched state has no retained frontier");
      }
      states.push_back(&qwen);
      items.push_back({
          .executor = &qwen.executor(),
          .token_id = advance.token,
          .position = static_cast<std::uint32_t>(qwen.position()),
      });
    }

    const auto frontiers = hip::QwenGpuExecutor::ForwardTokenBatch(items);
    if (frontiers.size() != states.size()) {
      throw std::runtime_error(
          "Qwen batched decode returned an invalid frontier count");
    }
    for (std::size_t index = 0; index < states.size(); ++index) {
      states[index]->set_position(states[index]->position() + 1);
      states[index]->set_frontier(frontiers[index]);
    }
  }

  [[nodiscard]] std::size_t CheckpointPosition(
      const TextRunnerState& state) const override {
    return RequireQwenState(state).position();
  }
  void PrepareCancellation(TextRunnerState& state) const override {
    RequireQwenState(state).PrepareCancellation();
  }

  [[nodiscard]] std::size_t SnapshotPayloadBytes(
      const TextRunnerState& state) const override {
    return RequireQwenState(state).SnapshotPayloadBytes();
  }

  [[nodiscard]] std::unique_ptr<TextRunnerSnapshot> Snapshot(
      const TextRunnerState& state) const override {
    const auto& qwen = RequireQwenState(state);
    if (!qwen.frontier().has_value()) {
      throw std::logic_error("Qwen state has no exact frontier to snapshot");
    }
    return std::make_unique<QwenTextRunnerSnapshot>(
        model_,
        qwen.executor().SaveSnapshot(
            static_cast<std::uint32_t>(qwen.position())),
        qwen.position(), qwen.frontier(), qwen.CopyFrontierLogits(),
        qwen.pending_tokens(), qwen.SaveVerifierSnapshot());
  }

  void RestoreOrFork(TextRunnerState& state,
                     const TextRunnerSnapshot& snapshot) const override {
    const auto* qwen_snapshot =
        dynamic_cast<const QwenTextRunnerSnapshot*>(&snapshot);
    if (qwen_snapshot == nullptr ||
        qwen_snapshot->model.get() != model_.get() ||
        qwen_snapshot->snapshot == nullptr ||
        !qwen_snapshot->frontier.has_value()) {
      throw std::invalid_argument(
          "Qwen snapshot does not belong to this model");
    }
    auto& restored = RequireQwenState(state);
    if (restored.speculative() !=
        (qwen_snapshot->verifier_snapshot != nullptr)) {
      throw std::invalid_argument(
          "Qwen snapshot speculative mode does not match the destination");
    }
    restored.executor().RestoreSnapshot(*qwen_snapshot->snapshot);
    restored.set_position(qwen_snapshot->position);
    restored.set_frontier(*qwen_snapshot->frontier);
    restored.RestoreFrontierLogits(qwen_snapshot->frontier_logits);
    restored.RestorePendingTokens(qwen_snapshot->pending_tokens);
    if (qwen_snapshot->verifier_snapshot != nullptr) {
      restored.RestoreVerifierSnapshot(*qwen_snapshot->verifier_snapshot);
    }
  }

  [[nodiscard]] std::size_t PersistentSnapshotPayloadBytes(
      const TextRunnerSnapshot& snapshot) const override {
    const auto* qwen_snapshot =
        dynamic_cast<const QwenTextRunnerSnapshot*>(&snapshot);
    const bool speculative = dflash_model_ != nullptr;
    if (qwen_snapshot == nullptr ||
        qwen_snapshot->model.get() != model_.get() ||
        qwen_snapshot->snapshot == nullptr ||
        !qwen_snapshot->frontier.has_value() ||
        (qwen_snapshot->verifier_snapshot != nullptr) != speculative ||
        qwen_snapshot->position != qwen_snapshot->snapshot->ValidContext() ||
        qwen_snapshot->pending_tokens.size() > kQwenMaxResumeTokens ||
        qwen_snapshot->frontier_logits.size() !=
            model_->GetConfig().vocab_size) {
      throw std::invalid_argument(
          "Qwen persistent snapshot does not belong to this runner");
    }
    const std::size_t logits_bytes = CheckedPersistentAdd(
        0, qwen_snapshot->frontier_logits.size() * sizeof(float));
    const std::size_t verifier_payload_bytes =
        qwen_snapshot->verifier_snapshot != nullptr
            ? qwen_snapshot->verifier_snapshot->PersistentPayloadBytes()
            : 0;
    return CheckedPersistentAdd(
        CheckedPersistentAdd(
            CheckedPersistentAdd(
                kQwenPersistentSnapshotHeaderBytes,
                qwen_snapshot->snapshot->CompactPayloadBytes()),
            logits_bytes),
        verifier_payload_bytes);
  }

  [[nodiscard]] std::size_t SerializePersistentSnapshot(
      const TextRunnerSnapshot& snapshot,
      std::span<std::uint8_t> destination) const override {
    const auto* qwen_snapshot =
        dynamic_cast<const QwenTextRunnerSnapshot*>(&snapshot);
    const std::size_t expected_bytes = PersistentSnapshotPayloadBytes(snapshot);
    if (qwen_snapshot == nullptr || destination.size() != expected_bytes) {
      throw std::invalid_argument(
          "Qwen persistent snapshot destination size is invalid");
    }
    const std::size_t gpu_payload_bytes =
        qwen_snapshot->snapshot->CompactPayloadBytes();
    const std::size_t logits_bytes =
        qwen_snapshot->frontier_logits.size() * sizeof(float);
    const std::size_t verifier_payload_bytes =
        qwen_snapshot->verifier_snapshot != nullptr
            ? qwen_snapshot->verifier_snapshot->PersistentPayloadBytes()
            : 0;
    // Nested serializers and the logits copy overwrite the payload completely.
    // Only this header has reserved bytes that need deterministic zeroing.
    std::fill_n(destination.begin(), kQwenPersistentSnapshotHeaderBytes,
                std::uint8_t{0});
    std::copy(kQwenPersistentSnapshotMagic.begin(),
              kQwenPersistentSnapshotMagic.end(), destination.begin());
    PutLittleEndian<std::uint32_t>(destination, 8,
                                   kQwenPersistentPayloadVersion);
    PutLittleEndian<std::uint32_t>(
        destination, 12,
        static_cast<std::uint32_t>(kQwenPersistentSnapshotHeaderBytes));
    PutLittleEndian<std::uint64_t>(
        destination, 16, static_cast<std::uint64_t>(qwen_snapshot->position));
    PutLittleEndian<std::uint32_t>(destination, 24, *qwen_snapshot->frontier);
    PutLittleEndian<std::uint32_t>(destination, 28,
                                   (qwen_snapshot->verifier_snapshot != nullptr
                                        ? kQwenPersistentSpeculativeFlag
                                        : 0U) |
                                       (!qwen_snapshot->pending_tokens.empty()
                                            ? kQwenPersistentPendingTokenFlag
                                            : 0U));
    PutLittleEndian<std::uint64_t>(
        destination, 32,
        static_cast<std::uint64_t>(qwen_snapshot->frontier_logits.size()));
    PutLittleEndian<std::uint64_t>(
        destination, 40, static_cast<std::uint64_t>(gpu_payload_bytes));
    PutLittleEndian<std::uint64_t>(destination, 48,
                                   static_cast<std::uint64_t>(expected_bytes));
    PutLittleEndian<std::uint64_t>(
        destination, 56, static_cast<std::uint64_t>(verifier_payload_bytes));
    PutLittleEndian<std::uint32_t>(
        destination, 64,
        static_cast<std::uint32_t>(qwen_snapshot->pending_tokens.size()));
    for (std::size_t i = 0; i < qwen_snapshot->pending_tokens.size(); ++i)
      PutLittleEndian<std::uint32_t>(destination,
                                     72 + i * sizeof(std::uint32_t),
                                     qwen_snapshot->pending_tokens[i]);
    const std::size_t gpu_offset = kQwenPersistentSnapshotHeaderBytes;
    const std::size_t logits_offset =
        CheckedPersistentAdd(gpu_offset, gpu_payload_bytes);
    const std::size_t verifier_offset =
        CheckedPersistentAdd(logits_offset, logits_bytes);
    const std::size_t written = qwen_snapshot->snapshot->SerializeCompact(
        destination.subspan(gpu_offset, gpu_payload_bytes));
    if (written != gpu_payload_bytes) {
      throw std::runtime_error(
          "Qwen compact snapshot serializer returned the wrong byte count");
    }
    std::memcpy(destination.data() + logits_offset,
                qwen_snapshot->frontier_logits.data(), logits_bytes);
    if (qwen_snapshot->verifier_snapshot != nullptr) {
      const std::size_t verifier_written =
          qwen_snapshot->verifier_snapshot->SerializePersistent(
              destination.subspan(verifier_offset, verifier_payload_bytes));
      if (verifier_written != verifier_payload_bytes) {
        throw std::runtime_error(
            "Qwen verifier serializer returned the wrong byte count");
      }
    }
    return destination.size();
  }

  void RestorePersistentSnapshot(
      TextRunnerState& state,
      std::span<const std::uint8_t> payload) const override {
    auto& restored = RequireQwenState(state);
    if (payload.size() < kQwenPersistentSnapshotHeaderBytes ||
        !std::equal(kQwenPersistentSnapshotMagic.begin(),
                    kQwenPersistentSnapshotMagic.end(), payload.begin()) ||
        GetLittleEndian<std::uint32_t>(payload, 8) !=
            kQwenPersistentPayloadVersion ||
        GetLittleEndian<std::uint32_t>(payload, 12) !=
            kQwenPersistentSnapshotHeaderBytes) {
      throw std::invalid_argument("Qwen persistent snapshot header is invalid");
    }
    const std::size_t position =
        PersistentSizeFromU64(GetLittleEndian<std::uint64_t>(payload, 16));
    const TextRunnerToken frontier =
        GetLittleEndian<std::uint32_t>(payload, 24);
    const std::uint32_t flags = GetLittleEndian<std::uint32_t>(payload, 28);
    const std::size_t logits_count =
        PersistentSizeFromU64(GetLittleEndian<std::uint64_t>(payload, 32));
    const std::size_t gpu_payload_bytes =
        PersistentSizeFromU64(GetLittleEndian<std::uint64_t>(payload, 40));
    const std::size_t total_bytes =
        PersistentSizeFromU64(GetLittleEndian<std::uint64_t>(payload, 48));
    const std::size_t verifier_payload_bytes =
        PersistentSizeFromU64(GetLittleEndian<std::uint64_t>(payload, 56));
    const bool speculative = (flags & kQwenPersistentSpeculativeFlag) != 0;
    const bool has_pending_token =
        (flags & kQwenPersistentPendingTokenFlag) != 0;
    const std::uint32_t pending_count =
        GetLittleEndian<std::uint32_t>(payload, 64);
    if (position == 0 || position > max_context_ ||
        position > std::numeric_limits<std::uint32_t>::max() ||
        (flags & ~(kQwenPersistentSpeculativeFlag |
                   kQwenPersistentPendingTokenFlag)) != 0 ||
        has_pending_token != (pending_count != 0) ||
        pending_count > kQwenMaxResumeTokens ||
        GetLittleEndian<std::uint32_t>(payload, 68) != 0 ||
        GetLittleEndian<std::uint32_t>(payload, 108) != 0 ||
        speculative != restored.speculative() ||
        frontier >= model_->GetConfig().vocab_size ||
        logits_count != model_->GetConfig().vocab_size ||
        logits_count >
            std::numeric_limits<std::size_t>::max() / sizeof(float) ||
        gpu_payload_bytes == 0 ||
        speculative != (verifier_payload_bytes != 0) ||
        total_bytes != payload.size()) {
      throw std::invalid_argument(
          "Qwen persistent snapshot metadata is invalid");
    }
    std::vector<TextRunnerToken> pending_tokens;
    for (std::size_t i = 0; i < kQwenMaxResumeTokens; ++i) {
      const auto token = GetLittleEndian<std::uint32_t>(
          payload, 72 + i * sizeof(std::uint32_t));
      if (i < pending_count) {
        if (token >= model_->GetConfig().vocab_size)
          throw std::invalid_argument("Qwen snapshot pending token is invalid");
        pending_tokens.push_back(token);
      } else if (token != 0) {
        throw std::invalid_argument(
            "Qwen snapshot has nonzero reserved tokens");
      }
    }
    const std::size_t logits_bytes = logits_count * sizeof(float);
    const std::size_t gpu_offset = kQwenPersistentSnapshotHeaderBytes;
    const std::size_t logits_offset =
        CheckedPersistentAdd(gpu_offset, gpu_payload_bytes);
    const std::size_t verifier_offset =
        CheckedPersistentAdd(logits_offset, logits_bytes);
    if (CheckedPersistentAdd(verifier_offset, verifier_payload_bytes) !=
        payload.size()) {
      throw std::invalid_argument(
          "Qwen persistent snapshot payload size is invalid");
    }

    std::vector<float> frontier_logits(logits_count);
    std::memcpy(frontier_logits.data(), payload.data() + logits_offset,
                logits_bytes);
    restored.executor().RestoreCompactSnapshot(
        payload.subspan(gpu_offset, gpu_payload_bytes),
        static_cast<std::uint32_t>(position));
    if (speculative) {
      restored.RestoreVerifierPersistentSnapshot(
          payload.subspan(verifier_offset, verifier_payload_bytes));
    }
    restored.set_position(position);
    restored.set_frontier(frontier);
    restored.RestoreFrontierLogits(std::move(frontier_logits));
    restored.RestorePendingTokens(pending_tokens);
  }

private:
  [[nodiscard]] std::size_t MaximumDecodeBatchWidth() const noexcept {
    const std::size_t rows_per_session = dflash_model_ != nullptr ? 8 : 1;
    return std::clamp<std::size_t>(max_context_ / rows_per_session, 1, 8);
  }

  mutable models::qwen::vision::ImageCache image_cache_;
  std::shared_ptr<const hip::QwenGpuModel> model_;
  std::shared_ptr<const hip::QwenDFlashGpuModel> dflash_model_;
  std::uint32_t max_context_;
  speculative::SpeculativeOptions speculative_options_;
  hip::QwenExecutionPolicy execution_policy_;
  std::optional<TextRunnerPersistenceDescriptor> persistence_;
};


}  // namespace cointos_control
