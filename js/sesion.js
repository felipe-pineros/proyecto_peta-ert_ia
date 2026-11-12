// PET Alert · Sesión y llamadas a la API (compartido por index.html y app.html).
//
// - supabase-js se usa SOLO para registrarse, iniciar sesión y renovar la sesión.
// - Todo lo demás pasa por nuestra API (/api/...) enviando el token del usuario.
// - La configuración pública (URL y publishable key) la entrega el backend en /api/config,
//   así no hay claves escritas en el código del frontend.
(function () {
  'use strict';

  let clientPromise = null;

  function getClient() {
    if (!clientPromise) {
      clientPromise = fetch('/api/config')
        .then((r) => {
          if (!r.ok) throw new Error('No se pudo cargar la configuración del servidor');
          return r.json();
        })
        .then((cfg) => window.supabase.createClient(cfg.supabase_url, cfg.supabase_publishable_key, {
          auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
        }))
        .catch((err) => { clientPromise = null; throw err; });
    }
    return clientPromise;
  }

  async function getSession() {
    const client = await getClient();
    const { data } = await client.auth.getSession();
    return data.session;
  }

  class ApiError extends Error {
    constructor(status, message) {
      super(message);
      this.status = status;
    }
  }

  // Traduce las respuestas de error de la API a un mensaje para la persona.
  function errorMessage(data, status) {
    if (data && typeof data.detail === 'string') return data.detail;
    if (data && Array.isArray(data.detail)) {
      return data.detail.map((d) => String(d.msg || '').replace(/^Value error, /, '')).join('. ');
    }
    if (status === 401) return 'Tu sesión terminó. Inicia sesión de nuevo.';
    if (status === 413) return 'El archivo es demasiado grande.';
    return 'Ocurrió un error (' + status + '). Intenta de nuevo.';
  }

  // api('/api/reports', { method: 'POST', body: {...} })  ·  api(url, { method: 'POST', form: FormData })
  async function api(path, options) {
    const { method = 'GET', body, form } = options || {};
    const session = await getSession();
    const headers = {};
    if (session) headers.Authorization = 'Bearer ' + session.access_token;
    let payload;
    if (form) {
      payload = form;
    } else if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
      payload = JSON.stringify(body);
    }
    let response;
    try {
      response = await fetch(path, { method, headers, body: payload });
    } catch (e) {
      throw new ApiError(0, 'No hay conexión con el servidor.');
    }
    if (response.status === 204) return null;
    let data = null;
    try { data = await response.json(); } catch (e) { /* respuesta sin JSON */ }
    if (!response.ok) throw new ApiError(response.status, errorMessage(data, response.status));
    return data;
  }

  // Mensajes de Supabase Auth (en inglés) → español.
  function authMessage(error) {
    const msg = String((error && error.message) || error || '');
    const map = [
      [/already registered|already been registered/i, 'Ya existe una cuenta con ese correo. Inicia sesión.'],
      [/invalid login credentials/i, 'Correo o contraseña incorrectos.'],
      [/email not confirmed/i, 'Todavía no confirmas tu correo. Revisa tu bandeja de entrada (y el spam).'],
      [/password should be at least|weak password/i, 'La contraseña es muy débil: usa al menos 8 caracteres.'],
      [/rate limit|too many/i, 'Demasiados intentos. Espera unos minutos y vuelve a intentarlo.'],
      [/invalid email|unable to validate email/i, 'El correo no es válido.'],
      [/anonymous sign-ins are disabled/i, 'El reporte sin cuenta está desactivado en este momento. Crea una cuenta para reportar.'],
      [/signups not allowed/i, 'El registro de cuentas está desactivado en este momento.'],
    ];
    for (const [re, text] of map) if (re.test(msg)) return text;
    return msg || 'No se pudo completar la operación.';
  }

  // ¿Es una sesión de invitado (reporte rápido sin cuenta)?
  function isAnonymous(session) {
    return Boolean(session && session.user && session.user.is_anonymous);
  }

  window.PetAlert = { getClient, getSession, api, ApiError, authMessage, isAnonymous };
})();
