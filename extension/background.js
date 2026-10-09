// Listen with ReadRush: sends the page (or the selection) to the ReadRush desktop app.
const APP = "http://127.0.0.1:47653/read";

function grabPage() {
  const sel = String(window.getSelection() || "").trim();
  if (sel.length > 20) return { title: document.title, url: location.href, text: sel };
  const pick = document.querySelector("article") || document.querySelector("main") ||
               document.querySelector("[role=main]") || document.body;
  const clone = pick.cloneNode(true);
  clone.querySelectorAll("script,style,noscript,nav,footer,header,aside,form,button,svg,iframe")
       .forEach(e => e.remove());
  return { title: document.title, url: location.href, text: (clone.innerText || "").trim() };
}

async function send(tab, payload) {
  try {
    const r = await fetch(APP, { method: "POST", headers: { "Content-Type": "application/json" },
                                 body: JSON.stringify(payload) });
    if (!r.ok) throw new Error("HTTP " + r.status);
    chrome.action.setBadgeText({ tabId: tab.id, text: "▶" });
    chrome.action.setBadgeBackgroundColor({ color: "#8B7CFF" });
    setTimeout(() => chrome.action.setBadgeText({ tabId: tab.id, text: "" }), 2500);
  } catch (e) {
    chrome.action.setBadgeText({ tabId: tab.id, text: "!" });
    chrome.action.setBadgeBackgroundColor({ color: "#FF6B7A" });
    chrome.scripting.executeScript({ target: { tabId: tab.id },
      func: () => alert("ReadRush isn't running. Open the ReadRush app, then try again.") });
  }
}

async function listen(tab, selectionText) {
  if (selectionText && selectionText.trim().length > 0) {
    return send(tab, { title: tab.title, url: tab.url, text: selectionText });
  }
  const [res] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: grabPage });
  if (res && res.result && res.result.text) send(tab, res.result);
}

chrome.action.onClicked.addListener(tab => listen(tab));

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({ id: "rr-sel", title: "Listen to selection with ReadRush", contexts: ["selection"] });
  chrome.contextMenus.create({ id: "rr-page", title: "Listen to this page with ReadRush", contexts: ["page"] });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  listen(tab, info.menuItemId === "rr-sel" ? info.selectionText : "");
});
