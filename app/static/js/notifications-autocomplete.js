// Minimal autocomplete/suggestion helper for notifications form
// Provides comma-separated suggestions for users and teams fields.
(function(){
  function ajax(url, cb) {
    var xhr = new XMLHttpRequest();
    xhr.open('GET', url, true);
    // Ensure cookies are sent (in case auth is cookie-based)
    try { xhr.withCredentials = true; } catch (e) {}
    xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
    xhr.setRequestHeader('Accept', 'application/json');
    xhr.onreadystatechange = function(){
      if(xhr.readyState === 4){
        if (xhr.status >= 200 && xhr.status < 300) {
          try{
            cb(null, JSON.parse(xhr.responseText));
          } catch(e){
            console.debug('[ns-autocomplete] parse error, responseText:', xhr.responseText);
            cb(e);
          }
        } else {
          console.debug('[ns-autocomplete] non-2xx response', xhr.status, xhr.responseText);
          cb(new Error('HTTP ' + xhr.status));
        }
      }
    };
    xhr.send();
  }

  function createDropdown() {
    var d = document.createElement('div');
    d.className = 'ns-autocomplete-dropdown';
  // Use fixed positioning to avoid clipping by transformed/overflow parents
  d.style.position = 'fixed';
  d.style.zIndex = 99999;
    // Visual styles are delegated to CSS via the .ns-autocomplete-dropdown class
    return d;
  }

  // simple debounce
  function debounce(fn, wait){
    var t = null;
    return function(){
      var args = arguments;
      clearTimeout(t);
      t = setTimeout(function(){ fn.apply(null, args); }, wait);
    };
  }

  function attach(input, type){
    var dropdown = null;
    function close(){ if(dropdown && dropdown.parentNode) dropdown.parentNode.removeChild(dropdown); dropdown = null; }

    function getLastToken(value){
      var parts = value.split(',');
      return parts[parts.length-1].trim();
    }

    function setToken(value, newToken){
      var parts = value.split(',');
      parts[parts.length-1] = ' ' + newToken;
      return parts.join(',').replace(/^\s+/, '');
    }

    function fetchAndShow(q){
      console.debug('[ns-autocomplete] fetch suggestions for', type, q);
      var url = '/auth/notifications/suggestions?type=' + encodeURIComponent(type) + '&q=' + encodeURIComponent(q || '');
      ajax(url, function(err, res){
        if(err){ console.debug('[ns-autocomplete] ajax error', err); close(); return; }
        if(!res || !res.results || !res.results.length){ console.debug('[ns-autocomplete] no results', res); close(); return; }
        close();
        dropdown = createDropdown();
        res.results.slice(0,50).forEach(function(item){
          var el = document.createElement('div');
          el.className = 'ns-autocomplete-item';
          // Visual/padding/hover handled via CSS
          el.textContent = item;
          el.addEventListener('mousedown', function(ev){
            ev.preventDefault();
            input.value = setToken(input.value, item);
            // normalize spacing
            input.value = input.value.split(',').map(function(p){ return p.trim(); }).filter(function(p){ return p; }).join(', ');
            close();
            input.focus();
          });
          dropdown.appendChild(el);
        });
  document.body.appendChild(dropdown);
  var rect = input.getBoundingClientRect();
  // Use fixed position so dropdown isn't clipped by parent stacking contexts
  dropdown.style.left = (rect.left) + 'px';
  dropdown.style.top = (rect.bottom) + 'px';
  dropdown.style.minWidth = Math.max(rect.width, 160) + 'px';
  console.debug('[ns-autocomplete] showed dropdown with', res.results.length, 'items');
      });
    }

    var debouncedFetch = debounce(function(){
      var val = input.value || '';
      var q = getLastToken(val);
      // allow empty q to show full suggestions
      fetchAndShow(q);
    }, 200);

    input.addEventListener('input', debouncedFetch);
    // show suggestions on focus even if empty
    input.addEventListener('focus', function(){
      var val = input.value || '';
      var q = getLastToken(val);
      fetchAndShow(q);
    });

    input.addEventListener('blur', function(){ setTimeout(close, 150); });
  }

  // On DOM ready attach to inputs with data-autocomplete attr
  document.addEventListener('DOMContentLoaded', function(){
    var usersInput = document.querySelector('input[name="users"][data-autocomplete="users"]');
    if(usersInput) attach(usersInput, 'users');
    var teamsInput = document.querySelector('input[name="teams"][data-autocomplete="teams"]');
    if(teamsInput) attach(teamsInput, 'teams');
  });
})();
