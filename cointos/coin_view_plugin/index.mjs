// This tool reads an immutable journal result. It cannot call any Coin controls.
export default {
  id: "cointos-coin-view",
  async setup(ctx) {
    await ctx.model.transform(editor => {
      for (const model of editor.list()) if (model.providerID !== "mirror") editor.remove(model.providerID, model.id);
    });
    await ctx.tool.transform(editor => {
      for (const tool of editor.list()) editor.remove(tool.id);
      editor.add({
        name: "coin_observation",
        description: "Display an already recorded Coin tool call and its result.",
        input: { type: "object", properties: {
          name: { type: "string" }, arguments: { type: "object" } }, required: ["name", "arguments"] },
        async execute(input, context) {
          if (!/^[a-f0-9]{32}$/.test(context.id)) throw new Error("Invalid journal record");
          const response = await fetch(process.env.COINTOS_COIN_REPLAY_URL + "/result/" + context.id, {
            headers: { authorization: "Bearer " + process.env.COINTOS_COIN_REPLAY_TOKEN },
          });
          if (!response.ok) throw new Error("Recorded Coin result unavailable");
          const value = await response.json();
          return { content: [{ type: "text", text: typeof value === "string" ? value : JSON.stringify(value) }],
            metadata: { title: input.name } };
        },
      });
    });
    await ctx.tool.hook("execute.before", event => {
      if (event.tool !== "coin_observation") throw new Error("This window only displays Coin's journal.");
    });
  },
};
