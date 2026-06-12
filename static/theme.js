(function () {
  var STORAGE_KEY = 'comissao-app-theme';
  var root = document.documentElement;

  function getStored() {
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch (e) {
      return null;
    }
  }

  function setStored(value) {
    try {
      localStorage.setItem(STORAGE_KEY, value);
    } catch (e) {}
  }

  function applyTheme(theme) {
    if (theme === 'dark') {
      root.setAttribute('data-theme', 'dark');
    } else {
      root.setAttribute('data-theme', 'light');
    }
  }

  function toggleTheme() {
    var current = root.getAttribute('data-theme') || 'light';
    var next = current === 'light' ? 'dark' : 'light';
    setStored(next);
    applyTheme(next);
  }

  var btn = document.getElementById('themeToggle');
  if (btn) {
    btn.addEventListener('click', toggleTheme);
  }

  var saved = getStored();
  if (saved === 'dark' || saved === 'light') {
    applyTheme(saved);
  } else {
    applyTheme('light');
  }
})();
