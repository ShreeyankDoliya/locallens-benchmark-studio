const $ = selector => document.querySelector(selector);
const signup = new URLSearchParams(location.search).get('mode') === 'signup';
if (signup) {
  document.title = 'Create account · LocalLens';
  $('#auth-title').textContent = 'Make room for discovery.';
  $('#auth-subtitle').textContent = 'Create your LocalLens account.';
  $('#login-tab').classList.remove('selected');
  $('#signup-tab').classList.add('selected');
  $('#name-field').hidden = false;
  $('#display-name').required = true;
  $('#password').autocomplete = 'new-password';
  $('#password').minLength = 15;
  $('#password-hint').hidden = false;
  $('#submit-label').textContent = 'Create account';
  $('#switch-copy').textContent = 'Already have an account?';
  $('#switch-link').textContent = 'Sign in';
  $('#switch-link').href = 'login.html';
}
$('#toggle-password').addEventListener('click', () => {
  const show = $('#password').type === 'password';
  $('#password').type = show ? 'text' : 'password';
  $('#toggle-password').textContent = show ? 'Hide' : 'Show';
  $('#toggle-password').setAttribute('aria-label', show ? 'Hide password' : 'Show password');
  $('#toggle-password').setAttribute('aria-pressed', String(show));
});
// Keep credential submission disabled until an account backend is selected and connected.
$('#auth-form').addEventListener('submit', event => event.preventDefault());
