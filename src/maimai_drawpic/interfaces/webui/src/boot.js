(() => {
  "use strict";
  const U = window.DrawpicUI;
  async function start() {
    try {
      await U.bootstrap();
      const view = window.location.hash.slice(1);
      if (Object.hasOwn(U.views, view)) U.state.view = view;
      else if (view) U.replaceViewHash(U.state.view);
      await U.render();
    } catch (error) {
      const node = U.$("#load-error");
      node.textContent = error.message || String(error);
      node.hidden = false;
      U.$("#workspace-content").innerHTML = U.empty(
        "工作台暂时不可用",
        "请确认从 MaiBot 插件扩展页打开，插件已加载，再点击刷新。",
      );
      U.$("#connection").textContent = "连接未完成";
    }
  }
  start();
})();
