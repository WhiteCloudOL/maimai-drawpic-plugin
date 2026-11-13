(() => {
  "use strict";
  const U = window.DrawpicUI;
  const easing = "cubic-bezier(.2,.8,.2,1)", effects = new WeakMap(), segments = new WeakMap();
  const observed = new Set();
  const observer = new ResizeObserver(entries => {
    for (const { target } of entries) {
      if (target.isConnected) segments.get(target).position();
      else { observer.unobserve(target); observed.delete(target); }
    }
  });
  const reduced = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  function enter(element, distance = 5) {
    effects.get(element)?.cancel();
    if (reduced()) return;
    effects.set(element, element.animate([
      { opacity: .55, transform: `translateY(${distance}px)` },
      { opacity: 1, transform: "translateY(0)" },
    ], { duration: 220, easing }));
  }
  function loading(element, pending) {
    element.toggleAttribute("data-page-loading", pending);
    element.setAttribute("aria-busy", String(pending));
  }
  function segmented(root, fromTransform = null) {
    for (const element of observed) if (!element.isConnected) { observer.unobserve(element); observed.delete(element); }
    let controller = segments.get(root);
    if (!controller) {
      const indicator = root.querySelector('.mode-indicator') || document.createElement("span");
      indicator.classList.add("motion-segmented-indicator");
      indicator.setAttribute("aria-hidden", "true");
      if (!indicator.isConnected) root.prepend(indicator);
      root.classList.add("motion-segmented");
      const position = () => {
        const active = root.querySelector('[aria-pressed="true"]');
        if (!active || !root.offsetWidth) return;
        indicator.style.width = `${active.offsetWidth}px`;
        indicator.style.height = `${active.offsetHeight}px`;
        indicator.style.transform = `translate(${active.offsetLeft}px,${active.offsetTop}px)`;
      };
      controller = { indicator, position };
      segments.set(root, controller);
      observer.observe(root);
      observed.add(root);
      controller.position();
      requestAnimationFrame(() => { if (root.isConnected) root.classList.add("motion-ready"); });
    }
    controller.position();
    if (fromTransform && !reduced()) controller.indicator.animate([
      { transform: fromTransform }, { transform: controller.indicator.style.transform },
    ], { duration: 320, easing });
  }
  U.motion = { enter, loading, segmented };
})();
