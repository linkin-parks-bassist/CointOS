---
status: green
revised_at: "2026-11-17T09:02:13+11:00"
---

The Halogen engine refuses any prompt that contains a `<|image_pad|>` control token with no image pixels attached. It returns HTTP 400: "prompt token N is the image placeholder <|image_pad|> and no image covers it". The refusal is deterministic, so every retry of that conversation fails at the same token. The gateway reports the failure as "the thought failed on the model server", and clients such as OpenCode retry it indefinitely.

CointOS's `render` control op used to create such tokens in two ways:

- **Real image content parts.** A tool result carrying an image, such as Playwright's `browser_take_screenshot`, made the chat template emit `<|vision_start|><|image_pad|><|vision_end|>`. The control path never sends pixels.
- **Literal marker text.** Message, tool-output or tool-description text that quoted `<|image_pad|>` or any other chat marker was encoded as control tokens, because the whole rendered prompt went through `tok.encode`. This also let quoted `<|im_end|>`/`<|im_start|>` forge turn boundaries. The engine's own refusal message quotes `<|image_pad|>`, so the failure could spread to any agent that read it.

The current behavior has three parts:

1. `backend_halogen.render` replaces every non-text content part with the `IMAGE_OMITTED` text note before rendering. The model learns that an image existed and that it cannot see it. Real vision input through the control path is not implemented.
2. `halogen_control.render` uses the pinned frontend's own helpers from `__main__`: `shield_messages`/`shield_kwargs`, `tokenize_offsets` and `textify_pad_mentions`. Quoted markers stay text, and the template's structural markers stay control tokens. `install()` refuses a frontend that lacks these helpers.
3. `lanes.finish` carries the failure text to the gateway, which returns "the thought failed on the model server: <reason>" instead of a bare "try again".

The real tokenizer, probed inside the pinned container, confirms the fix. Previously, a quoted marker produced 2 image pads plus a forged `<|im_end|>` and `<|im_start|>`, and a raw image part produced 1 uncovered pad. Now both produce none, text round-trips exactly, and plain conversations tokenize identically. A live gateway request with a screenshot tool result that also quoted `<|image_pad|>` returned a normal answer in 1.7 s. tests/test_backend_halogen.py covers the render path.

`halogen_control.py` is bind-mounted into the container as a single file. An edit replaces the inode, so the running container keeps the old code until it is recreated (`podman stop`/`rm cointos-halogen`). The daemon relaunches it on demand.
