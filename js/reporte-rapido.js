// PET Alert · Reporte rápido "Encontré una mascota" de la página principal (sin cuenta).
//
// Flujo:
//   1. Si la persona no tiene sesión, Supabase le crea una sesión ANÓNIMA (invitado, sin
//      correo ni contraseña). Requiere "Allow anonymous sign-ins" activado en Supabase.
//   2. Se crea el reporte "found" con la API normal (especie, fecha = ahora, ubicación, contacto).
//   3. Se sube la foto y se publica.
// La base de datos (migración 4) limita a los invitados: solo reportes encontrados, con
// contacto, y sin ver los reportes de los demás.
(function () {
  'use strict';

  const form = document.getElementById('quick-form');
  if (!form) return;
  const { api, getClient, getSession, authMessage } = window.PetAlert;

  const MAX_BYTES = 10 * 1024 * 1024;
  const TYPES = ['image/jpeg', 'image/png', 'image/webp'];
  const $ = (id) => document.getElementById(id);
  const photoInput = $('qr-photo');
  const photoBox = $('qr-photo-box');
  const mapEl = $('qr-map');
  const phone = $('qr-phone');
  const email = $('qr-email');
  const msg = $('qr-msg');
  const msgText = $('qr-msg-text');
  const againBtn = $('qr-again');
  const submitBtn = form.querySelector('.form-submit');
  const btnLabel = submitBtn.querySelector('.btn-label');

  let point = null;   // { lat, lng } marcado en el mapa
  let picker = null;  // mapa (se crea cuando la sección se acerca a la pantalla)
  let previewUrl = null;

  // ---------------------------------------------------------------- mapa
  function initMap() {
    if (picker) return picker;
    if (!window.L || !window.PetMap) {
      setError('qr-map', 'No se pudo cargar el mapa. Revisa tu conexión y recarga la página.');
      return null;
    }
    picker = window.PetMap.picker(mapEl, null, (p) => {
      point = p;
      setError('qr-map', '');
    });
    return picker;
  }
  if ('IntersectionObserver' in window) {
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) { initMap(); io.disconnect(); }
    }, { rootMargin: '300px' });
    io.observe(mapEl);
  } else {
    initMap();
  }

  $('qr-locate').addEventListener('click', async () => {
    const p = initMap();
    if (!p) return;
    try { await p.locate(); } catch (err) { setError('qr-map', err.message); }
  });

  // ---------------------------------------------------------------- foto
  function clearPreview() {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = null;
    photoBox.querySelectorAll('img.preview, .change').forEach((n) => n.remove());
  }

  function photoError() {
    const f = photoInput.files[0];
    if (!f) return 'Agrega una foto de la mascota.';
    if (!TYPES.includes(f.type)) return 'La foto debe ser JPEG, PNG o WebP.';
    if (f.size > MAX_BYTES) return 'La foto pesa más de 10 MB.';
    return '';
  }

  photoInput.addEventListener('change', () => {
    clearPreview();
    const error = photoError();
    setError('qr-photo', photoInput.files[0] ? error : '');
    if (error) return;
    previewUrl = URL.createObjectURL(photoInput.files[0]);
    const img = document.createElement('img');
    img.className = 'preview';
    img.alt = 'Foto elegida';
    img.src = previewUrl;
    const change = document.createElement('span');
    change.className = 'change';
    change.textContent = 'Cambiar foto';
    photoBox.append(img, change);
  });

  // ---------------------------------------------------------------- validación
  const ERROR_TARGET = { 'qr-photo': photoBox, 'qr-map': mapEl };

  function setError(id, message) {
    const errorEl = $('err-' + id);
    const target = ERROR_TARGET[id] || $(id);
    if (errorEl) { errorEl.textContent = message; errorEl.hidden = !message; }
    if (target) target.classList.toggle('invalid', Boolean(message));
  }

  function contactErrors() {
    const p = phone.value.trim();
    const e = email.value.trim();
    const out = { 'qr-phone': '', 'qr-email': '' };
    if (p && !/^[0-9\s+()-]{7,40}$/.test(p)) out['qr-phone'] = 'Ingresa un teléfono válido.';
    if (e && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e)) out['qr-email'] = 'Ingresa un correo válido.';
    if (!p && !e) out['qr-phone'] = 'Deja un teléfono o un correo para que el dueño pueda contactarte.';
    return out;
  }

  [phone, email].forEach((input) => input.addEventListener('input', () => {
    const errs = contactErrors();
    // Mientras escribe solo se muestran errores de formato, no el de "falta contacto".
    if (!phone.value.trim() && !email.value.trim()) errs['qr-phone'] = '';
    Object.entries(errs).forEach(([id, m]) => setError(id, m));
  }));

  function validate() {
    const errors = { 'qr-photo': photoError(), ...contactErrors() };
    errors['qr-map'] = point ? '' : 'Marca en el mapa dónde viste la mascota.';
    let first = null;
    for (const id of ['qr-photo', 'qr-map', 'qr-phone', 'qr-email']) {
      setError(id, errors[id]);
      if (errors[id] && !first) first = id;
    }
    if (first) {
      const target = first === 'qr-photo' ? photoInput : (first === 'qr-map' ? mapEl : $(first));
      target.focus({ preventScroll: true });
      (ERROR_TARGET[first] || target).scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    return !first;
  }

  // ---------------------------------------------------------------- envío
  function setLoading(loading, label) {
    submitBtn.disabled = loading;
    submitBtn.classList.toggle('is-loading', loading);
    btnLabel.textContent = label;
  }

  function showMessage(text, isError) {
    msgText.textContent = text;
    msg.style.display = 'flex';
    msg.style.background = isError ? 'rgba(231,111,81,0.12)' : '';
    msg.style.color = isError ? '#9a3412' : '';
    againBtn.hidden = Boolean(isError);
  }

  // Botones para difundir el hallazgo (js/compartir.js), con la foto que la persona eligió.
  const shareBox = $('qr-share');
  function showShare(report, file) {
    shareBox.querySelectorAll('.share-row, .share-note').forEach((n) => n.remove());
    if (!window.PetShare) return;
    const note = document.createElement('p');
    note.className = 'share-note';
    note.textContent = 'El texto no incluye tu teléfono ni tu correo.';
    shareBox.append(window.PetShare.panel({ report, photoFile: file }), note);
    shareBox.hidden = false;
  }

  async function ensureSession() {
    if (await getSession()) return;  // ya tiene sesión (cuenta normal o invitado anterior)
    const client = await getClient();
    const { error } = await client.auth.signInAnonymously();
    if (error) throw new Error(authMessage(error));
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    msg.style.display = 'none';
    if (!validate()) return;

    setLoading(true, 'Publicando…');
    let reportId = null;
    try {
      await ensureSession();
      const body = {
        type: 'found',
        species: form.querySelector('input[name="qr-species"]:checked').value,
        event_at: new Date().toISOString(),
        lat: point.lat,
        lng: point.lng,
      };
      if (phone.value.trim()) body.contact_phone = phone.value.trim();
      if (email.value.trim()) body.contact_email = email.value.trim();
      const report = await api('/api/reports', { method: 'POST', body });
      reportId = report.id;

      setLoading(true, 'Subiendo foto…');
      const fd = new FormData();
      fd.append('file', photoInput.files[0]);
      await api('/api/reports/' + reportId + '/photos', { method: 'POST', form: fd });

      setLoading(true, 'Publicando…');
      const published = await api('/api/reports/' + reportId + '/publish', { method: 'POST' });
      showShare(published, photoInput.files[0]);

      form.querySelectorAll('input, button.qr-locate').forEach((f) => { f.disabled = true; });
      setLoading(true, 'Reporte publicado');
      showMessage('¡Gracias por ayudar! Publicamos el reporte. Si su familia la reportó como perdida, ' +
        'verá la posible coincidencia y, si confirma que es su mascota, podrá contactarte.');
    } catch (err) {
      // Si el borrador quedó a medias (p. ej. falló la foto), se retira para no dejar basura.
      if (reportId) {
        try { await api('/api/reports/' + reportId + '/withdraw', { method: 'POST' }); } catch (e2) { /* ignorar */ }
      }
      setLoading(false, 'Publicar reporte');
      showMessage(err.message || 'No se pudo publicar el reporte. Intenta de nuevo.', true);
    }
  });

  againBtn.addEventListener('click', () => {
    form.reset();
    form.querySelectorAll('input, button.qr-locate').forEach((f) => { f.disabled = false; });
    clearPreview();
    msg.style.display = 'none';
    shareBox.hidden = true;
    setLoading(false, 'Publicar reporte');
    // Se conserva el punto del mapa: lo normal es reportar otra mascota en el mismo lugar.
    photoInput.focus({ preventScroll: true });
    photoBox.scrollIntoView({ behavior: 'smooth', block: 'center' });
  });
})();
