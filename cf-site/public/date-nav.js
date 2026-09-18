(function(){
  function qs(name){
    return new URLSearchParams(location.search).get(name);
  }
  function go(id){
    if(!id) return;
    if(id === window.__PICKS_LATEST__){
      location.href = "/";
      return;
    }
    location.href = "/days/" + id + "/";
  }
  async function boot(){
    const res = await fetch("/days.json", {cache:"no-store"});
    const data = await res.json();
    window.__PICKS_LATEST__ = data.latest;
    const current = document.documentElement.getAttribute("data-picks-date") || data.latest;
    const bar = document.createElement("div");
    bar.className = "date-nav";
    bar.innerHTML = '<span>日期</span>' +
      '<label><input type="date" id="picksDate"/></label>' +
      '<label>已发布 <select id="picksSelect"></select></label>' +
      '<a class="latest" href="/">今天最新</a>';
    const hdr = document.querySelector(".hdr") || document.body;
    hdr.appendChild(bar);
    const dateInput = bar.querySelector("#picksDate");
    const sel = bar.querySelector("#picksSelect");
    data.days.forEach(function(d){
      const opt = document.createElement("option");
      opt.value = d.id;
      opt.textContent = d.label;
      if(d.id === current) opt.selected = true;
      sel.appendChild(opt);
    });
    dateInput.value = current;
    const ids = data.days.map(function(d){ return d.id; });
    dateInput.min = ids[ids.length-1] || current;
    dateInput.max = data.latest;
    sel.addEventListener("change", function(){ go(sel.value); });
    dateInput.addEventListener("change", function(){
      const v = dateInput.value;
      if(ids.indexOf(v) >= 0) go(v);
      else alert("这一天还没有发布选品");
    });
  }
  if(document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
