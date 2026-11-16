// Native OpenCode 2 hooks. Original session/tool diagnostics remain untouched.
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

function observedContext() {
  try {
    const argv = JSON.parse(process.env.COINTOS_COMPACTION_CONTEXT_COMMAND);
    const text = execFileSync(argv[0], argv.slice(1), {
      encoding: "utf8", timeout: 4000, maxBuffer: 16000,
      env: { ...process.env, PYTHONPATH: fileURLToPath(new URL("../..", import.meta.url)) },
      stdio: ["ignore", "pipe", "pipe"],
    }).trim();
    if (!text) throw new Error("empty context");
    return text;
  } catch {
    return "Current task/file facts unavailable. Re-read cointos_task and inspect assigned files before acting.";
  }
}

export function anchor(response, text) {
  // The managed gateway speaks OpenAI chat completions. Inject before its finish
  // notification, so the native compactor persists this text as part of its summary.
  const suffix = "\n\n[CointOS observed context; separate from the model summary]\n" + text +
    "\nAccepted test bindings are not evidence that their files or build targets exist in the assigned directory. " +
    "This snapshot can become stale; re-read cointos_task before changing work.\n[/CointOS observed context]";
  const headers = new Headers(response.headers);
  headers.delete("content-length");
  if (!headers.get("content-type")?.includes("text/event-stream")) {
    return response.json().then(body => {
      if (body.choices?.[0]?.message) body.choices[0].message.content += suffix;
      else throw new Error("CointOS: unrecognised compaction response; factual anchor withheld");
      return new Response(JSON.stringify(body), { status: response.status, headers });
    });
  }
  const decoder = new TextDecoder(), encoder = new TextEncoder();
  let pending = "", inserted = false;
  function line(value, controller) {
    if (value.startsWith("data:") && !inserted) {
      const raw = value.slice(5).trim();
      if (raw && raw !== "[DONE]") {
        const chunk = JSON.parse(raw);
        if (chunk.choices?.some(choice => choice.finish_reason)) {
          const addition = { ...chunk, choices: [{ index: 0, delta: { content: suffix }, finish_reason: null }] };
          controller.enqueue(encoder.encode("data: " + JSON.stringify(addition) + "\n\n"));
          inserted = true;
        }
      }
    }
    controller.enqueue(encoder.encode(value + "\n"));
  }
  return new Response(response.body.pipeThrough(new TransformStream({
    transform(chunk, controller) {
      pending += decoder.decode(chunk, { stream: true });
      const lines = pending.split("\n"); pending = lines.pop();
      for (const value of lines) line(value, controller);
    },
    flush(controller) {
      pending += decoder.decode();
      if (pending) line(pending, controller);
      if (!inserted) throw new Error("CointOS: compaction stream ended without its factual anchor");
    },
  })), { status: response.status, headers });
}

export default {
  id: "cointos",
  async setup(ctx) {
    await ctx.model.transform(editor => {
      for (const model of editor.list()) {
        if (model.providerID !== (process.env.COINTOS_PROVIDER || "cointos")) editor.remove(model.providerID, model.id);
      }
    });
    const harness = readFileSync(new URL("../../roles/_harness.md", import.meta.url), "utf8");
    await ctx.session.hook("model.request", event => {
      event.headers["X-CointOS-Harness"] = event.kind === "primary" ? "opencode2" : "opencode2-aux";
    });
    await ctx.session.hook("title", event => { event.result = process.env.COINTOS_TASK_ID || "CointOS"; });
    await ctx.session.hook("context", event => {
      for (const part of event.system) {
        if (part.text?.startsWith("You are an AI agent running in OpenCode,")) part.text = harness;
        for (const instruction of part.metadata?.experimental?.instructions || []) {
          if (instruction.key === "core/codemode" && part.text?.includes(instruction.text)) {
            part.text = part.text.replace(instruction.text,
              "<cointos_native_tools>\n" + instruction.text + "\n</cointos_native_tools>");
          }
        }
      }
    });
    await ctx.session.hook("http.response", async event => {
      if (event.kind === "compaction" && process.env.COINTOS_COMPACTION_CONTEXT_COMMAND && event.response.ok) {
        event.response = await anchor(event.response, observedContext());
      }
    });
    await ctx.tool.transform(editor => {
      // Delegation and task ownership belong to CointOS. V2's execute remains
      // available for its native MCP dispatch; the MCP broker owns authority.
      for (const id of ["subagent", "task", "skill", "todowrite", "question"]) editor.remove(id);
      for (const tool of editor.list()) {
        if (tool.options?.namespace === "cointos") {
          // V2's JSON-schema decoder silently strips unknown object fields,
          // even with additionalProperties:false. Preserve them until the
          // CointOS broker can reject the original request without changing it.
          editor.update(tool.id, entry => {
            entry.input = { ...entry.input, additionalProperties: true };
          });
        }
        if (tool.options?.namespace === "opencode" && /^(session_|worktree_)/.test(tool.name)) editor.remove(tool.id);
        if (tool.options?.namespace === "knowledgetrees") {
          const allowed = new Set(["kt_lookup", "kt_read"]);
          if (["integrator", "manager", "gardener", "tree-auditor", "operator"].includes(process.env.COINTOS_ROLE)) {
            for (const name of ["grep", "add", "rewrite", "renew", "prove", "audit", "status", "mv", "combine", "rm"]) allowed.add("kt_" + name);
          }
          if (!allowed.has(tool.name)) editor.remove(tool.id);
        }
      }
    });
  },
};
