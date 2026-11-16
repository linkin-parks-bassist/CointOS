export default {
  id: "cointos-private",
  async setup(ctx) {
    await ctx.model.transform(editor => {
      for (const model of editor.list()) {
        if (model.providerID !== "cointos") editor.remove(model.providerID, model.id);
      }
    });
    await ctx.session.hook("title", event => { event.result = "Private local session"; });
    await ctx.session.hook("model.request", event => {
      event.headers["X-CointOS-Harness"] = "opencode2";
      event.headers["X-CointOS-Prefix-Layout"] = "stable-v1";
    });
  },
};
