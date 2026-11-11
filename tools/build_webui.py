"""把模块化页面源码组合成宿主可直接读取的单文件 HTML。"""

from pathlib import Path
import base64


def build() -> Path:
    root = Path(__file__).resolve().parents[1]
    source = root / "src" / "maimai_drawpic" / "interfaces" / "webui" / "src"
    html = (source / "index.html").read_text(encoding="utf-8")
    icon = base64.b64encode((root / "assets" / "icon.png").read_bytes()).decode("ascii")
    html = html.replace("{{workspace:icon}}", "data:image/png;base64," + icon)
    css = (source / "style.css").read_text(encoding="utf-8")
    names = (
        "app",
        "forms/select",
        "forms/options",
        "forms/controls",
        "forms/collections",
        "forms",
        "platform-models",
        "platform-comfyui",
        "platforms",
        "studio",
        "tasks",
        "settings",
        "logs",
        "boot",
    )
    scripts = "\n".join((source / f"{name}.js").read_text(encoding="utf-8") for name in names)
    html = html.replace("<!-- workspace:styles -->", f"<style>\n{css}\n</style>")
    html = html.replace(
        "<!-- workspace:scripts -->", "<script>\n" + scripts.replace("</script", "<\\/script") + "\n</script>"
    )
    target = source.parent / "index.html"
    target.write_text(html, encoding="utf-8", newline="\n")
    return target


if __name__ == "__main__":
    print(build())
