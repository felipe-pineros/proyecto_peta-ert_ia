// PET Alert · Formulario de registro de la landing (index.html).
// Crea la cuenta en Supabase Auth. El perfil se crea solo en la base (trigger),
// con el nombre enviado en display_name. El teléfono se guarda en el perfil al
// primer inicio de sesión (ver app.js), porque puede que aún no haya sesión si
// Supabase exige confirmar el correo.
(function () {
  'use strict';

  const form = document.getElementById('petalert-form');
  if (!form) return;
  const confirmMsg = document.getElementById('confirm-msg');
  const confirmText = document.getElementById('confirm-text');
  const submitBtn = form.querySelector('.form-submit');
  const btnLabel = submitBtn.querySelector('.btn-label');

  const validators = {
    nombre: (v) => (v.trim().length >= 2 && v.trim().length <= 80) ? '' : 'Ingresa tu nombre completo.',
    email: (v) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v.trim()) ? '' : 'Ingresa un correo válido.',
    telefono: (v) => (v.trim() === '' || /^[0-9\s+()-]{7,40}$/.test(v.trim())) ? '' : 'Ingresa un teléfono válido.',
    password: (v) => v.length >= 8 ? '' : 'La contraseña debe tener al menos 8 caracteres.',
  };

  function setFieldError(name, message) {
    const input = document.getElementById(name);
    const errorEl = document.getElementById('err-' + name);
    if (!input || !errorEl) return;
    errorEl.textContent = message;
    errorEl.hidden = !message;
    input.classList.toggle('invalid', Boolean(message));
    if (message) input.setAttribute('aria-invalid', 'true');
    else input.removeAttribute('aria-invalid');
  }

  Object.keys(validators).forEach((name) => {
    const input = document.getElementById(name);
    input.addEventListener('input', () => setFieldError(name, validators[name](input.value)));
  });

  function setLoading(loading, label) {
    submitBtn.disabled = loading;
    submitBtn.classList.toggle('is-loading', loading);
    btnLabel.textContent = label;
  }

  function showMessage(text, isError) {
    confirmText.textContent = text;
    confirmMsg.style.display = 'flex';
    confirmMsg.style.background = isError ? 'rgba(231,111,81,0.12)' : '';
    confirmMsg.style.color = isError ? '#9a3412' : '';
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    let firstInvalid = null;
    Object.keys(validators).forEach((name) => {
      const input = document.getElementById(name);
      const message = validators[name](input.value);
      setFieldError(name, message);
      if (message && !firstInvalid) firstInvalid = input;
    });
    if (firstInvalid) { firstInvalid.focus(); return; }

    const value = (id) => document.getElementById(id).value.trim();
    setLoading(true, 'Creando cuenta...');
    confirmMsg.style.display = 'none';
    try {
      const client = await window.PetAlert.getClient();
      const { data, error } = await client.auth.signUp({
        email: value('email'),
        password: document.getElementById('password').value,
        options: {
          data: { display_name: value('nombre'), phone: value('telefono') || null },
          emailRedirectTo: window.location.origin + '/app.html',
        },
      });
      if (error) throw error;
      // Si el correo ya existía, Supabase no da error (por privacidad) pero no crea identidad.
      if (data.user && Array.isArray(data.user.identities) && data.user.identities.length === 0) {
        throw new Error('already registered');
      }
      form.querySelectorAll('input').forEach((f) => { f.disabled = true; });
      if (data.session) {
        showMessage('¡Cuenta creada! Te llevamos a la aplicación...');
        setLoading(true, 'Cuenta creada');
        window.location.href = 'app.html';
      } else {
        showMessage('¡Cuenta creada! Te enviamos un correo a ' + value('email') +
          '. Ábrelo y confirma tu cuenta; después podrás iniciar sesión.');
        setLoading(true, 'Revisa tu correo');
        submitBtn.style.opacity = '0.7';
      }
    } catch (err) {
      setLoading(false, 'Crear cuenta');
      showMessage(window.PetAlert.authMessage(err), true);
    }
  });

  // Si ya hay sesión, el enlace del menú dice "Mi cuenta".
  window.PetAlert.getSession().then((session) => {
    const link = document.getElementById('nav-login');
    if (session && link) link.textContent = 'Mi cuenta';
  }).catch(() => { /* sin servidor: la landing sigue funcionando */ });
})();
