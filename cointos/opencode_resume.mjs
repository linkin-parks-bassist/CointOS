// The run supervisor authorizes one unfinished-turn resume through OpenCode's
// native message upsert. The CLI still receives text; the conversation does not.
import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

export default async ({ client, directory } = {}) => {
  let used = false;
  const anchored = new Set();
  return {
    "experimental.text.complete": async (input, output) => {
      const command = process.env.COINTOS_COMPACTION_CONTEXT_COMMAND;
      if (!command || !client?.session?.message) return;
      const key = JSON.stringify([input.sessionID, input.messageID, input.partID]);
      if (anchored.has(key)) return;
      let info;
      try {
        const response = await client.session.message({
          path: { id: input.sessionID, messageID: input.messageID },
          query: { directory }, signal: AbortSignal.timeout(1500),
        });
        info = response.data?.info;
      } catch {
        console.warn("CointOS: summary metadata unavailable; factual anchor omitted");
        return;
      }
      if (info?.role !== "assistant" || info.summary !== true ||
          info.id !== input.messageID || info.sessionID !== input.sessionID) return;
      let context;
      try {
        const argv = JSON.parse(command);
        context = execFileSync(argv[0], argv.slice(1), {
          encoding: "utf8", timeout: 4000, maxBuffer: 16000,
          env: { ...process.env, PYTHONPATH: fileURLToPath(new URL("..", import.meta.url)) },
          stdio: ["ignore", "pipe", "pipe"],
        }).trim();
        if (!context) throw new Error("empty context");
      } catch {
        context = "Current task/checkout facts unavailable. Re-read cointos_task and inspect the checkout before acting.";
      }
      output.text += "\n\n[CointOS observed context; separate from the model summary]\n" + context +
        "\nAccepted test bindings are not evidence that their files or build targets exist in this checkout. " +
        "This snapshot can become stale; re-read cointos_task before changing work.\n[/CointOS observed context]";
      anchored.add(key);
    },
    "chat.headers": async (input, output) => {
      if (process.env.COINTOS_STRUCTURED_COMPACTION === "1" && input.agent === "compaction") {
        output.headers["X-CointOS-Summary"] = "structured-v1";
      }
    },
    "chat.message": async (input, output) => {
      const path = process.env.COINTOS_RESUME_PACKET;
      if (used || !path) return;
      let packet;
      try {
        packet = JSON.parse(readFileSync(path, "utf8"));
      } catch (error) {
        if (error.code === "ENOENT") return;
        throw error;
      }
      if (input.sessionID !== packet.info.sessionID || output.parts.length !== 1 ||
          output.parts[0].type !== "text" || output.parts[0].text !== "Continue.") {
        throw new Error("Unfinished-turn resume does not match its launch");
      }
      for (const key of Object.keys(output.message)) delete output.message[key];
      Object.assign(output.message, packet.info);
      output.parts.splice(0);
      used = true;
    },
  };
};
