// A conversion server may read/migrate storage; it must never execute a task.
export default {
  id: "cointos-migration",
  async setup(ctx) {
    await ctx.model.transform(editor => {
      for (const model of editor.list()) editor.remove(model.providerID, model.id);
    });
    await ctx.session.hook("model.request", () => { throw new Error("Session conversion cannot generate"); });
    await ctx.tool.hook("execute.before", () => { throw new Error("Session conversion cannot execute tools"); });
  },
};
