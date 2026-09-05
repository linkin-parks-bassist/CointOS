# Model Inventory Assessment and Residency Plan

## Current Model Situation

Based on my investigation of the system, I can identify the following key points about the current model inventory and configuration:

### 1. Current Model Configuration

From configuration files, I can see that:
- The system is configured with a policy of 3 resident LLM slots
- Control plane uses Qwen3.8-27B-GGUF (pinned)
- Fast front uses GLM-4.7-Flash-GGUF (pinned)
- Workers use various models including Qwen3-Coder-30B-A3B-Instruct-GGUF for review work

### 2. Available Models

However, I found no actual model files (.gguf) on the system. The system references models like:
- Qwen3.8-27B-GGUF
- GLM-4.7-Flash-GGUF
- Qwen3-Coder-30B-A3B-Instruct-GGUF
- Qwen3.5-4B-GGUF
- Qwen3.5-8B-GGUF

But the actual GGUF files are not present in the filesystem. The system appears to be configured to run with these models but they aren't currently installed or loaded.

### 3. Vision Capability

The system references Qwen3.8-27B-GGUF in configuration, but no actual vision-capable model files exist. The model configuration doesn't indicate whether the Qwen3.8 model actually supports vision processing or if it's just labeled as such.

### 4. Model Availability

The system appears to be designed to work with a local LLM model server that would be accessible at port 13305, but no actual model files are present in the file system.

## Assessment of Vision Capability

While the configuration indicates Qwen3.8-27B-GGUF as the control plane model, there is no actual model file present to verify if this model has functional vision capabilities. The "vision" label in the configuration doesn't confirm end-to-end vision functionality.

## Recommendations for 100GB Pool

### 1. Vision Capability for Control Plane

The system should have a vision-capable model for the control plane. Without actual vision models installed, it cannot truly function as a vision-capable control plane.

### 2. Big Fancy Model for Serious Work

The system is designed to work with large models, but currently lacks the GGUF files for:
- Qwen3.6-27B-FP16-vLLM (51.8GB)
- Qwen3-Coder-Next (44.7GB)
- LMX-Omni-52B-Halo (44.77GB)

### 3. Pinning/Residency Plan

Current policy has resident_llm_slots=3 but with only 3 slots currently defined, and with a 100GB GTT pool, we should consider increasing resident slots.

## Proposed Plan

1. **Vision Capability**: Since no vision-capable models exist, a new download would be warranted to get a vision-capable control plane.

2. **Big Fancy Models**: Since no large models are currently installed, we should consider downloading and pinning the biggest available models.

3. **Pinning/Residency Layout**: With 100GB available and ~77GB free, we should:
   - Increase resident_llm_slots to 4 or 5
   - Pin the largest models with highest utility
   - Keep at least one large model resident for serious work
   - Maintain current control plane model as primary

4. **Caution with Small Models**: As requested, we should treat small models with extra skepticism for architectural decisions, audits, and innovations.

The current system configuration suggests it's designed for large models but lacks the actual model files necessary for full functionality.
