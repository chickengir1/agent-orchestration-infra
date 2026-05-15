// Injected via page.evaluate. Returns { view, actions, meta }.
// Arg: { masks: string[] } — selectors to hide from extraction.

(({ masks }) => {
  const isVisible = (el) => {
    if (!el || !(el instanceof Element)) return false;
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) return false;
    const s = getComputedStyle(el);
    return s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
  };
  const accessibleName = (el) => {
    const a = el.getAttribute('aria-label'); if (a) return a.trim();
    const lb = el.getAttribute('aria-labelledby');
    if (lb) { const r = document.getElementById(lb); if (r) return (r.textContent||'').trim(); }
    const t = (el.textContent||'').trim(); if (t) return t.slice(0,120);
    const ph = el.getAttribute('placeholder'); if (ph) return ph.trim();
    const ti = el.getAttribute('title'); if (ti) return ti.trim();
    return '';
  };
  const locusOf = (el) => {
    const trail = []; let c = el.parentElement;
    while (c && c !== document.body) {
      const role = c.getAttribute('role');
      const tag = c.tagName.toLowerCase();
      if ((role && ['main','navigation','banner','contentinfo','region','dialog','complementary','search','form'].includes(role))
       || ['main','nav','header','footer','aside','section','article','form','dialog'].includes(tag)) {
        const lab = c.getAttribute('aria-label') || '';
        trail.unshift(`${role||tag}${lab?`[${lab}]`:''}`);
        if (trail.length >= 3) break;
      }
      c = c.parentElement;
    }
    return trail.join(' > ');
  };
  const applyMask = (t) => {
    if (!t) return t;
    return t
      .replace(/\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?/g,'{TS}')
      .replace(/\d+\s*(초|분|시간|일|주|개월|년)\s*전/g,'{REL}')
      .replace(/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/g,'{UUID}')
      .replace(/\b\d{6,}\b/g,'{ID}');
  };
  const masked = new Set();
  for (const sel of (masks||[])) {
    try { document.querySelectorAll(sel).forEach(n => masked.add(n)); } catch(e){}
  }
  const isMasked = (el) => { let c=el; while(c){ if(masked.has(c)) return true; c=c.parentElement; } return false; };

  const title = document.title || '';
  const headings = [];
  document.querySelectorAll('h1,h2,h3,h4,h5,h6').forEach(h => {
    if (!isVisible(h) || isMasked(h)) return;
    headings.push({ level: +h.tagName.slice(1), text: applyMask((h.textContent||'').trim()).slice(0,200) });
  });
  const landmarks = [];
  document.querySelectorAll('[role=main],[role=navigation],[role=banner],[role=contentinfo],[role=region],[role=dialog],[role=complementary],[role=search],[role=form],main,nav,header,footer,aside,form,dialog').forEach(el => {
    if (!isVisible(el) || isMasked(el)) return;
    landmarks.push({ role: el.getAttribute('role')||el.tagName.toLowerCase(), name: (el.getAttribute('aria-label')||'').trim(), childCount: el.children.length });
  });
  const texts = [];
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => {
      const t = (n.nodeValue||'').trim(); if (!t) return NodeFilter.FILTER_REJECT;
      const p = n.parentElement; if (!p || !isVisible(p) || isMasked(p)) return NodeFilter.FILTER_REJECT;
      const tag = p.tagName.toLowerCase();
      if (['script','style','noscript'].includes(tag)) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    }
  });
  while (w.nextNode()) {
    const raw = (w.currentNode.nodeValue||'').trim();
    if (raw.length < 2) continue;
    texts.push(applyMask(raw).slice(0,200));
    if (texts.length >= 500) break;
  }
  const components = {};
  const classes = {};
  document.querySelectorAll('*').forEach(el => {
    if (!isVisible(el)) return;
    const t = el.tagName.toLowerCase();
    if (t.startsWith('app-') || t.includes('-')) components[t] = (components[t]||0)+1;
    const cl = el.classList;
    for (let i = 0; i < cl.length; i++) {
      const c = cl[i];
      if (!c || c.length > 64) continue;
      if (/^(cdk-|ng-|mat-mdc-|_ngcontent|_nghost)/.test(c)) continue;
      if (/^[a-z0-9_-]*\d{4,}/i.test(c)) continue;
      classes[c] = (classes[c]||0)+1;
    }
  });
  const emptyStates = [];
  document.querySelectorAll('[role=alert],[data-empty],.empty-state,.no-data,.no-result,.error-state').forEach(el => {
    if (!isVisible(el)) return;
    emptyStates.push({ kind: el.getAttribute('role')==='alert'?'alert':'empty', text: applyMask((el.textContent||'').trim()).slice(0,200) });
  });

  const actSel = ['button','[role=button]','a[href]','input','textarea','select','[contenteditable]','[role=menuitem]','[role=tab]','[role=switch]','[role=checkbox]','[role=radio]','[role=link]'].join(',');
  const actions = [];
  document.querySelectorAll(actSel).forEach(el => {
    if (isMasked(el)) return;
    const visible = isVisible(el);
    const tag = el.tagName.toLowerCase();
    const role = el.getAttribute('role') || (tag==='a'?'link':tag==='button'?'button':tag==='input'?(el.getAttribute('type')||'textbox'):tag);
    let target = null;
    if (tag === 'a') {
      const h = el.getAttribute('href');
      if (h) { try { const u = new URL(h, location.href); target = u.pathname + u.search; } catch { target = h; } }
    }
    actions.push({
      role,
      name: applyMask(accessibleName(el)).slice(0,120),
      state: {
        disabled: el.hasAttribute('disabled') || el.getAttribute('aria-disabled')==='true',
        pressed: el.getAttribute('aria-pressed')==='true',
        expanded: el.getAttribute('aria-expanded')==='true',
        selected: el.getAttribute('aria-selected')==='true',
        required: el.hasAttribute('required') || el.getAttribute('aria-required')==='true',
        visible,
      },
      target,
      locus: locusOf(el),
    });
  });

  return {
    view: { title: applyMask(title), headings, landmarks, texts, components, classes, emptyStates },
    actions,
    meta: { url: location.href, pathname: location.pathname, origin: location.origin },
  };
});
