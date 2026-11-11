// PET Alert · Lógica de la aplicación (app.html).
//
// Vistas (se eligen con el "#" de la dirección):
//   #explorar · #mis-reportes · #nuevo · #nuevo/lost · #nuevo/found · #editar/<id>
//   #reporte/<id> · #coincidencia/<id> · #notificaciones
//
// Seguridad: el contenido escrito por usuarios se inserta SIEMPRE como texto
// (textContent), nunca como HTML, para evitar inyección de código (XSS).
(function () {
  'use strict';

  const { api, getClient, getSession, authMessage } = window.PetAlert;
  const $ = (sel, root) => (root || document).querySelector(sel);
  const PAGE_SIZE = 12;
  const MAX_PHOTOS = 5;
  const MAX_PHOTO_BYTES = 10 * 1024 * 1024;

  let me = null;              // mi perfil
  let speciesList = [];       // [{code, name_es}]
  let mounted = [];           // funciones a ejecutar cuando la vista ya está en pantalla
  let renderToken = 0;
  let badgeTimer = null;

  // -------------------------------------------------------------------------
  // Utilidades de interfaz
  // -------------------------------------------------------------------------
  function el(tag, props, ...children) {
    const node = document.createElement(tag);
    if (props) {
      for (const [key, value] of Object.entries(props)) {
        if (value === null || value === undefined || value === false) continue;
        if (key === 'class') node.className = value;
        else if (key === 'text') node.textContent = value;
        else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
        else if (value === true) node.setAttribute(key, '');
        else node.setAttribute(key, String(value));
      }
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  function onMount(fn) { mounted.push(fn); }

  function toast(message, isError) {
    const box = $('#toast');
    box.textContent = message;
    box.classList.toggle('is-error', Boolean(isError));
    box.hidden = false;
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => { box.hidden = true; }, isError ? 6000 : 3500);
  }

  function selectEl(id, options, value) {
    const s = el('select', { id });
    for (const [v, label] of options) s.append(el('option', { value: v, text: label }));
    if (value !== undefined && value !== null) s.value = value;
    return s;
  }

  function field(labelText, input, opts) {
    const o = opts || {};
    return el('div', { class: o.full ? 'full' : null },
      el('label', { for: input.id, text: labelText }), input,
      o.hint ? el('span', { class: 'hint', text: o.hint }) : null);
  }

  function viewHead(kicker, title, text, action) {
    return el('div', { class: 'view-head' },
      el('div', null, el('div', { class: 'kicker', text: kicker }), el('h2', { text: title }),
        text ? el('p', { text }) : null),
      action || null);
  }

  function emptyBox(text, action) {
    return el('div', { class: 'empty' }, el('p', { text }), action || null);
  }

  function busy(button, label) {
    const old = button.textContent;
    button.disabled = true;
    button.textContent = label;
    return () => { button.disabled = false; button.textContent = old; };
  }

  // -------------------------------------------------------------------------
  // Textos
  // -------------------------------------------------------------------------
  const TYPE = { lost: 'Perdida', found: 'Encontrada' };
  const STATUS = { draft: 'Borrador', active: 'Publicado', resolved: 'Resuelto', withdrawn: 'Retirado' };
  const SIZE = { small: 'Pequeño', medium: 'Mediano', large: 'Grande' };
  const MATCH_STATUS = { suggested: 'Posible coincidencia', confirmed: 'Confirmada', discarded: 'Descartada' };
  const NOTIF = {
    new_match: 'Hay una posible coincidencia para uno de tus reportes',
    match_confirmed: 'Confirmaron una coincidencia: ya puedes ver el contacto',
    match_discarded: 'Una posible coincidencia fue descartada',
  };
  const speciesName = (code) => (speciesList.find((s) => s.code === code) || {}).name_es || code;
  const fmtDate = (iso) => (iso ? new Date(iso).toLocaleString('es-CO', { dateStyle: 'medium', timeStyle: 'short' }) : '—');
  const pct = (x) => Math.round(Number(x) * 100) + ' %';
  const km = (x) => Number(x).toLocaleString('es-CO', { maximumFractionDigits: 1 }) + ' km';
  const badge = (cls, text) => el('span', { class: 'badge badge-' + cls, text });

  function toLocalInput(iso) {
    const d = iso ? new Date(iso) : new Date();
    const pad = (n) => String(n).padStart(2, '0');
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + 'T' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  }

  // -------------------------------------------------------------------------
  // Fotos (URL firmadas temporales, con caché corta)
  // -------------------------------------------------------------------------
  const photoCache = new Map();
  async function photoUrl(id) {
    const hit = photoCache.get(id);
    if (hit && hit.until > Date.now()) return hit.url;
    const data = await api('/api/photos/' + id + '/url');
    photoCache.set(id, { url: data.url, until: Date.now() + (data.expires_in - 30) * 1000 });
    return data.url;
  }

  function photoImg(id, cls, alt) {
    const img = el('img', { class: cls || 'thumb', alt: alt || 'Foto de la mascota', loading: 'lazy' });
    if (id) photoUrl(id).then((url) => { img.src = url; }).catch(() => { img.alt = 'Foto no disponible'; });
    return img;
  }

  function firstPhoto(report) {
    const ready = (report.photos || []).filter((p) => p.status === 'ready');
    return ready.length ? ready[0].id : null;
  }

  // -------------------------------------------------------------------------
  // Tarjetas
  // -------------------------------------------------------------------------
  function reportTitle(r) {
    return (r.type === 'lost' ? 'Se perdió · ' : 'Se encontró · ') + speciesName(r.species);
  }

  function reportCard(r) {
    return el('a', { class: 'report-card', href: '#reporte/' + r.id },
      photoImg(firstPhoto(r), 'thumb', 'Foto de ' + reportTitle(r)),
      el('div', { class: 'report-card-body' },
        el('div', { class: 'badges' },
          badge(r.type, TYPE[r.type]),
          r.is_mine ? badge(r.status, STATUS[r.status]) : null),
        el('h3', { text: reportTitle(r) }),
        el('p', { class: 'meta', text: [r.color, SIZE[r.size], r.breed].filter(Boolean).join(' · ') }),
        el('p', { class: 'meta', text: (r.location_label || 'Ubicación en el mapa') + ' · ' + fmtDate(r.event_at) })));
  }

  // -------------------------------------------------------------------------
  // Vista: explorar reportes activos
  // -------------------------------------------------------------------------
  async function viewExplore() {
    const state = { offset: 0 };
    const grid = el('div', { class: 'card-grid' });
    const emptyHolder = el('div');
    const typeSel = selectEl('f-type', [['', 'Perdidas y encontradas'], ['lost', 'Mascotas perdidas'], ['found', 'Mascotas encontradas']]);
    const spSel = selectEl('f-species', [['', 'Todas las especies'], ...speciesList.map((s) => [s.code, s.name_es])]);
    typeSel.setAttribute('aria-label', 'Filtrar por tipo');
    spSel.setAttribute('aria-label', 'Filtrar por especie');
    const more = el('button', { class: 'btn btn-outline', type: 'button', hidden: true, text: 'Ver más' });

    async function load(reset) {
      if (reset) { state.offset = 0; grid.replaceChildren(); emptyHolder.replaceChildren(); }
      const params = new URLSearchParams({ limit: PAGE_SIZE, offset: state.offset });
      if (typeSel.value) params.set('type', typeSel.value);
      if (spSel.value) params.set('species', spSel.value);
      const rows = await api('/api/reports?' + params);
      rows.forEach((r) => grid.append(reportCard(r)));
      state.offset += rows.length;
      more.hidden = rows.length < PAGE_SIZE;
      if (!grid.children.length) {
        emptyHolder.append(emptyBox('No hay reportes publicados con estos filtros.',
          el('a', { class: 'btn btn-primary', href: '#nuevo', text: 'Crear un reporte' })));
      }
    }
    const reload = () => load(true).catch((e) => toast(e.message, true));
    typeSel.addEventListener('change', reload);
    spSel.addEventListener('change', reload);
    more.addEventListener('click', () => load(false).catch((e) => toast(e.message, true)));
    await load(true);

    return el('section', null,
      viewHead('Explorar', 'Mascotas reportadas', 'Reportes publicados por la comunidad, del más reciente al más antiguo. La ubicación que ves es aproximada (~1 km).'),
      el('div', { class: 'filters' }, typeSel, spSel),
      grid, emptyHolder,
      el('div', { class: 'btn-row', style: 'justify-content:center; margin-top:24px;' }, more));
  }

  // -------------------------------------------------------------------------
  // Vista: mis reportes
  // -------------------------------------------------------------------------
  async function viewMine() {
    const rows = await api('/api/reports/mine');
    const newBtn = el('a', { class: 'btn btn-coral', href: '#nuevo', text: '+ Nuevo reporte' });
    return el('section', null,
      viewHead('Mis reportes', 'Tus reportes', 'Aquí ves todos tus reportes (también borradores y cerrados) y sus posibles coincidencias.', newBtn),
      rows.length
        ? el('div', { class: 'card-grid' }, rows.map(reportCard))
        : emptyBox('Todavía no has creado reportes.', el('a', { class: 'btn btn-primary', href: '#nuevo', text: 'Crear mi primer reporte' })));
  }

  // -------------------------------------------------------------------------
  // Vista: detalle de un reporte
  // -------------------------------------------------------------------------
  async function viewReport(id) {
    const r = await api('/api/reports/' + id);
    const open = r.is_mine && (r.status === 'draft' || r.status === 'active');
    const ready = (r.photos || []).filter((p) => p.status === 'ready');

    // Fotos
    const main = photoImg(ready[0] && ready[0].id, 'photo-main', 'Foto principal de ' + reportTitle(r));
    const grid = el('div', { class: 'photo-grid' });
    ready.forEach((p, i) => {
      const thumb = photoImg(p.id, 'thumb', 'Foto ' + (i + 1));
      thumb.style.cursor = 'pointer';
      thumb.addEventListener('click', () => { photoUrl(p.id).then((u) => { main.src = u; }); });
      const removable = open && !(r.status === 'active' && ready.length <= 1);
      grid.append(el('div', { class: 'photo-item' }, thumb,
        removable ? el('button', { class: 'btn btn-danger', type: 'button', text: 'Quitar', onclick: async (e) => {
          e.stopPropagation();
          if (!confirm('¿Quitar esta foto?')) return;
          try { await api('/api/photos/' + p.id, { method: 'DELETE' }); toast('Foto eliminada'); route(); } catch (err) { toast(err.message, true); }
        } }) : null));
    });
    let addPhotos = null;
    if (open && ready.length < MAX_PHOTOS) {
      const input = el('input', { type: 'file', accept: 'image/jpeg,image/png,image/webp', multiple: true, id: 'add-photos' });
      input.addEventListener('change', async () => {
        const files = Array.from(input.files).slice(0, MAX_PHOTOS - ready.length);
        try {
          await uploadPhotos(r.id, files, (t) => toast(t));
          toast('Fotos agregadas');
        } catch (err) { toast(err.message, true); }
        route();
      });
      addPhotos = field('Agregar fotos (te quedan ' + (MAX_PHOTOS - ready.length) + ')', input, { hint: 'JPEG, PNG o WebP, máximo 10 MB cada una.' });
    }

    // Datos
    const facts = el('dl', { class: 'facts' });
    const fact = (k, v) => { if (v) facts.append(el('dt', { text: k }), el('dd', { text: v })); };
    fact('Tipo', r.type === 'lost' ? 'Mascota perdida' : 'Mascota encontrada');
    fact('Especie', speciesName(r.species));
    fact('Raza', r.breed);
    fact('Color', r.color);
    fact('Tamaño', SIZE[r.size]);
    fact('Rasgos', r.distinctive_features);
    fact(r.type === 'lost' ? 'Se perdió' : 'Se encontró', fmtDate(r.event_at));
    fact('Lugar', r.location_label);
    if (r.is_mine) fact('Estado', STATUS[r.status]);

    // Mapa
    const mapBox = el('div', { class: 'map-box', id: 'detail-map' });
    const exact = r.is_mine && r.private && r.private.exact_lat !== null && r.private.exact_lat !== undefined;
    onMount(() => {
      if (exact) window.PetMap.viewer(mapBox, r.private.exact_lat, r.private.exact_lng, false);
      else window.PetMap.viewer(mapBox, r.approx_lat, r.approx_lng, true);
    });

    const left = el('div', null,
      el('div', { class: 'panel' },
        el('div', { class: 'badges', style: 'margin-bottom:12px;' }, badge(r.type, TYPE[r.type]), r.is_mine ? badge(r.status, STATUS[r.status]) : null),
        ready.length ? main : el('div', { class: 'notice', text: 'Este reporte aún no tiene fotos.' }),
        ready.length > 1 || open ? el('div', { style: 'margin-top:14px;' }, grid) : null,
        addPhotos ? el('div', { style: 'margin-top:16px;' }, addPhotos) : null),
      el('div', { class: 'panel' }, el('h3', { text: 'Datos' }), facts));

    const right = el('div', null,
      el('div', { class: 'panel' },
        el('h3', { text: 'Ubicación' }), mapBox,
        el('p', { class: 'hint', text: exact ? 'Punto exacto: solo tú lo ves. Los demás ven un círculo aproximado de ~1 km.' : 'Ubicación aproximada (~1 km) para proteger la privacidad.' })));

    if (r.is_mine) {
      const p = r.private || {};
      const actions = el('div', { class: 'btn-row' });
      if (open) actions.append(el('a', { class: 'btn btn-outline', href: '#editar/' + r.id, text: 'Editar datos' }));
      if (r.status === 'draft') {
        actions.append(el('button', { class: 'btn btn-coral', type: 'button', text: 'Publicar', onclick: async (e) => {
          const done = busy(e.currentTarget, 'Publicando…');
          try { await api('/api/reports/' + r.id + '/publish', { method: 'POST' }); toast('Reporte publicado'); route(); } catch (err) { done(); toast(err.message, true); }
        } }));
      }
      if (open) {
        actions.append(el('button', { class: 'btn btn-danger', type: 'button', text: 'Retirar reporte', onclick: async (e) => {
          if (!confirm('¿Retirar este reporte? Dejará de verse y no podrás editarlo.')) return;
          const done = busy(e.currentTarget, 'Retirando…');
          try { await api('/api/reports/' + r.id + '/withdraw', { method: 'POST' }); toast('Reporte retirado'); route(); } catch (err) { done(); toast(err.message, true); }
        } }));
      }
      const contact = el('dl', { class: 'facts', style: 'margin-bottom:16px;' },
        el('dt', { text: 'Teléfono' }), el('dd', { text: p.contact_phone || '—' }),
        el('dt', { text: 'Correo' }), el('dd', { text: p.contact_email || '—' }));
      right.append(el('div', { class: 'panel' },
        el('h3', { text: 'Tu contacto (privado)' }),
        el('p', { class: 'hint', style: 'margin:-6px 0 12px;', text: 'Solo se comparte con la otra persona cuando se confirma una coincidencia.' }),
        contact, actions));

      // Posibles coincidencias
      const matchPanel = el('div', { class: 'panel' }, el('h3', { text: 'Posibles coincidencias' }));
      if (r.status === 'draft') {
        matchPanel.append(el('p', { class: 'muted', text: 'Publica el reporte para empezar a buscar coincidencias.' }));
      } else {
        const matches = await api('/api/reports/' + r.id + '/matches');
        if (!matches.length) {
          matchPanel.append(el('p', { class: 'muted', text: 'Aún no hay posibles coincidencias. Te avisaremos en "Avisos" cuando aparezca alguna.' }));
        } else {
          matchPanel.append(el('p', { class: 'hint', style: 'margin:-6px 0 12px;', text: 'Ordenadas por parecido de las fotos y cercanía. Son sugerencias: revisa con cuidado.' }));
          matchPanel.append(el('div', { class: 'match-list' }, matches.map(matchItem)));
        }
      }
      right.append(matchPanel);
    }

    return el('section', null,
      el('a', { class: 'back-link', href: r.is_mine ? '#mis-reportes' : '#explorar', text: '← Volver' }),
      viewHead(r.is_mine ? 'Mi reporte' : 'Reporte', reportTitle(r)),
      el('div', { class: 'detail-grid' }, left, right));
  }

  // -------------------------------------------------------------------------
  // Coincidencias
  // -------------------------------------------------------------------------
  function matchActions(m) {
    const row = el('div', { class: 'btn-row' });
    if (m.can_confirm) {
      row.append(el('button', { class: 'btn btn-primary btn-sm', type: 'button', text: 'Es mi mascota', onclick: async (e) => {
        if (!confirm('¿Confirmas que es tu mascota?\n\nAmbos reportes quedarán resueltos y se compartirán los datos de contacto entre las dos personas.')) return;
        const done = busy(e.currentTarget, 'Confirmando…');
        try { await api('/api/matches/' + m.id + '/confirm', { method: 'POST' }); toast('Coincidencia confirmada'); location.hash = '#coincidencia/' + m.id; route(); } catch (err) { done(); toast(err.message, true); }
      } }));
    }
    if (m.can_discard) {
      row.append(el('button', { class: 'btn btn-danger btn-sm', type: 'button', text: 'No es', onclick: async (e) => {
        if (!confirm('¿Descartar esta posible coincidencia? No volverá a sugerirse.')) return;
        const done = busy(e.currentTarget, 'Descartando…');
        try { await api('/api/matches/' + m.id + '/discard', { method: 'POST' }); toast('Coincidencia descartada'); route(); } catch (err) { done(); toast(err.message, true); }
      } }));
    }
    return row;
  }

  function matchItem(m) {
    const o = m.other_report;
    return el('div', { class: 'match-item' },
      photoImg(firstPhoto(o), 'thumb', 'Foto del otro reporte'),
      el('div', null,
        el('div', { class: 'badges', style: 'margin-bottom:6px;' }, badge(m.status, MATCH_STATUS[m.status])),
        el('p', null, el('span', { class: 'score', text: 'Parecido ' + pct(m.visual_score) }), ' · a ' + km(m.distance_km)),
        el('p', { class: 'muted', text: [speciesName(o.species), o.color, SIZE[o.size]].filter(Boolean).join(' · ') + ' · ' + fmtDate(o.event_at) }),
        el('div', { class: 'btn-row', style: 'margin-top:10px;' },
          el('a', { class: 'btn btn-outline btn-sm', href: '#coincidencia/' + m.id, text: 'Ver detalle' }),
          matchActions(m))));
  }

  async function viewMatch(id) {
    const m = await api('/api/matches/' + id);
    const o = m.other_report;
    const photos = (o.photos || []).filter((p) => p.status === 'ready');
    const mapBox = el('div', { class: 'map-box' });
    onMount(() => window.PetMap.viewer(mapBox, o.approx_lat, o.approx_lng, true));

    const facts = el('dl', { class: 'facts' });
    const fact = (k, v) => { if (v) facts.append(el('dt', { text: k }), el('dd', { text: v })); };
    fact('Especie', speciesName(o.species));
    fact('Raza', o.breed);
    fact('Color', o.color);
    fact('Tamaño', SIZE[o.size]);
    fact('Rasgos', o.distinctive_features);
    fact(o.type === 'lost' ? 'Se perdió' : 'Se encontró', fmtDate(o.event_at));
    fact('Lugar', o.location_label);

    let contact;
    if (m.contact) {
      const c = m.contact;
      contact = el('div', { class: 'contact-box' },
        el('strong', { text: 'Datos de contacto' }),
        el('dl', { class: 'facts', style: 'margin-top:8px;' },
          el('dt', { text: 'Nombre' }), el('dd', { text: c.display_name || '—' }),
          el('dt', { text: 'Teléfono' }), el('dd', { text: c.phone || '—' }),
          el('dt', { text: 'Correo' }), el('dd', { text: c.email || '—' })));
    } else if (m.status === 'suggested') {
      contact = el('p', { class: 'muted', text: m.can_confirm
        ? 'Si reconoces a tu mascota, confírmalo para ver el contacto de quien la encontró.'
        : 'El dueño de la mascota perdida debe confirmar la coincidencia para que se compartan los contactos.' });
    } else {
      contact = el('p', { class: 'muted', text: 'Esta coincidencia fue descartada.' });
    }

    return el('section', null,
      el('a', { class: 'back-link', href: '#reporte/' + m.my_report_id, text: '← Volver a mi reporte' }),
      viewHead('Coincidencia', MATCH_STATUS[m.status]),
      el('p', { class: 'notice', style: 'margin-bottom:20px;', text: 'El sistema sugiere que podría tratarse del mismo animal por el parecido de las fotos y la cercanía. No es una confirmación: compara bien las fotos y los rasgos.' }),
      el('div', { class: 'detail-grid' },
        el('div', null,
          el('div', { class: 'panel' },
            el('h3', { text: o.type === 'lost' ? 'Mascota perdida (de la otra persona)' : 'Mascota encontrada (por la otra persona)' }),
            photos.length ? el('div', { class: 'photo-grid' }, photos.map((p, i) => photoImg(p.id, 'thumb', 'Foto ' + (i + 1)))) : el('p', { class: 'muted', text: 'Sin fotos disponibles.' })),
          el('div', { class: 'panel' }, el('h3', { text: 'Datos' }), facts)),
        el('div', null,
          el('div', { class: 'panel' },
            el('h3', { text: 'Por qué se sugiere' }),
            el('dl', { class: 'facts' },
              el('dt', { text: 'Parecido de fotos' }), el('dd', { text: pct(m.visual_score) }),
              el('dt', { text: 'Distancia aprox.' }), el('dd', { text: km(m.distance_km) }),
              el('dt', { text: 'Puntaje total' }), el('dd', { text: pct(m.total_score) }))),
          el('div', { class: 'panel' }, el('h3', { text: 'Contacto' }), contact,
            el('div', { style: 'margin-top:14px;' }, matchActions(m))),
          el('div', { class: 'panel' }, el('h3', { text: 'Ubicación aproximada' }), mapBox))));
  }

  // -------------------------------------------------------------------------
  // Vista: avisos
  // -------------------------------------------------------------------------
  async function viewNotifications() {
    const list = await api('/api/notifications?limit=50');
    const items = list.map((n) => el('button', {
      class: 'notif-item' + (n.read_at ? '' : ' unread'), type: 'button',
      onclick: async () => {
        if (!n.read_at) { try { await api('/api/notifications/' + n.id + '/read', { method: 'POST' }); } catch (e) { /* no bloquea */ } }
        refreshBadge();
        location.hash = '#coincidencia/' + n.match_id;
      },
    }, el('span', null, el('strong', { text: NOTIF[n.kind] || 'Aviso' }), el('br'), el('small', { text: fmtDate(n.created_at) })),
    el('span', { class: 'link', text: 'Ver' })));
    return el('section', null,
      viewHead('Avisos', 'Tus avisos', 'Posibles coincidencias nuevas y decisiones sobre tus coincidencias.'),
      items.length ? el('div', { class: 'notif-list' }, items) : emptyBox('No tienes avisos todavía.'));
  }

  async function refreshBadge() {
    try {
      const unread = await api('/api/notifications?unread_only=true&limit=100');
      const b = $('#notif-badge');
      b.textContent = unread.length > 99 ? '99+' : String(unread.length);
      b.hidden = unread.length === 0;
    } catch (e) { /* silencioso */ }
  }

  // -------------------------------------------------------------------------
  // Subida de fotos
  // -------------------------------------------------------------------------
  function checkFiles(files) {
    for (const f of files) {
      if (!/^image\/(jpeg|png|webp)$/.test(f.type)) return 'La foto "' + f.name + '" no es JPEG, PNG ni WebP.';
      if (f.size > MAX_PHOTO_BYTES) return 'La foto "' + f.name + '" pesa más de 10 MB.';
    }
    return '';
  }

  async function uploadPhotos(reportId, files, onProgress) {
    const problem = checkFiles(files);
    if (problem) throw new Error(problem);
    let ok = 0;
    const errors = [];
    for (let i = 0; i < files.length; i++) {
      onProgress('Subiendo foto ' + (i + 1) + ' de ' + files.length + '…');
      const form = new FormData();
      form.append('file', files[i]);
      try {
        await api('/api/reports/' + reportId + '/photos', { method: 'POST', form });
        ok++;
      } catch (err) {
        errors.push(files[i].name + ': ' + err.message);
      }
    }
    if (errors.length) throw new Error('No se pudieron subir ' + errors.length + ' foto(s). ' + errors.join(' · '));
    return ok;
  }

  // -------------------------------------------------------------------------
  // Vista: crear o editar un reporte
  // -------------------------------------------------------------------------
  async function viewForm(opts) {
    const editing = Boolean(opts.editId);
    let report = null;
    let pets = [];
    if (editing) {
      report = await api('/api/reports/' + opts.editId);
      if (!report.is_mine || !(report.status === 'draft' || report.status === 'active')) {
        return emptyBox('Este reporte no se puede editar.', el('a', { class: 'btn btn-outline', href: '#mis-reportes', text: 'Volver' }));
      }
    } else {
      pets = await api('/api/pets');
    }
    const priv = (report && report.private) || {};
    let location = (report && priv.exact_lat !== undefined && priv.exact_lat !== null)
      ? { lat: Number(priv.exact_lat), lng: Number(priv.exact_lng) } : null;

    // --- campos ---
    const typeLost = el('input', { type: 'radio', name: 'f-type', value: 'lost' });
    const typeFound = el('input', { type: 'radio', name: 'f-type', value: 'found' });
    if (opts.type === 'found') typeFound.checked = true; else typeLost.checked = true;
    const typeBox = el('div', { class: 'full' },
      el('label', { text: '¿Qué quieres reportar?' }),
      el('div', { class: 'type-choice' },
        el('label', null, typeLost, 'Perdí mi mascota', el('small', { text: 'Publica a tu mascota como perdida' })),
        el('label', null, typeFound, 'Encontré una mascota', el('small', { text: 'Ayuda a que vuelva con su familia' }))));

    const petSel = selectEl('f-pet', [['', '+ Registrar una mascota nueva'], ...pets.map((p) => [p.id, (p.name || 'Sin nombre') + ' (' + speciesName(p.species) + ')'])]);
    const petName = el('input', { id: 'f-pet-name', maxlength: 80, placeholder: 'Ej. Toby' });
    const petNameField = field('Nombre de tu mascota (opcional)', petName);
    const petBox = el('div', { class: 'full', style: 'display:grid; gap:16px;' },
      field('¿Cuál de tus mascotas se perdió?', petSel), petNameField);

    const species = selectEl('f-species', speciesList.map((s) => [s.code, s.name_es]), report ? report.species : 'dog');
    const breed = el('input', { id: 'f-breed', maxlength: 80, placeholder: 'Opcional', value: (report && report.breed) || '' });
    const color = el('input', { id: 'f-color', maxlength: 80, placeholder: 'Ej. café con blanco', value: (report && report.color) || '', required: true });
    const size = selectEl('f-size', [['small', 'Pequeño'], ['medium', 'Mediano'], ['large', 'Grande']], report ? report.size : 'medium');
    const features = el('textarea', { id: 'f-features', maxlength: 1000, placeholder: 'Collar, manchas, cicatrices, comportamiento…' });
    features.value = (report && report.distinctive_features) || '';
    const eventAt = el('input', { id: 'f-event', type: 'datetime-local', value: toLocalInput(report && report.event_at), max: toLocalInput(), required: true });
    const place = el('input', { id: 'f-place', maxlength: 160, placeholder: 'Ej. Parque de Suba, Bogotá', value: (report && report.location_label) || '' });
    const phone = el('input', { id: 'f-phone', type: 'tel', maxlength: 40, placeholder: '300 000 0000', value: (editing ? priv.contact_phone : me.phone) || '' });
    const email = el('input', { id: 'f-email', type: 'email', maxlength: 254, value: (editing ? priv.contact_email : me.email) || '' });
    const photos = el('input', { id: 'f-photos', type: 'file', accept: 'image/jpeg,image/png,image/webp', multiple: true });
    const previews = el('div', { class: 'photo-grid', style: 'margin-top:10px;' });
    photos.addEventListener('change', () => {
      previews.replaceChildren();
      Array.from(photos.files).slice(0, MAX_PHOTOS).forEach((f) => {
        previews.append(el('img', { class: 'thumb', alt: 'Vista previa de ' + f.name, src: URL.createObjectURL(f) }));
      });
    });

    const mapBox = el('div', { class: 'map-box', id: 'form-map' });
    const mapStatus = el('span', { class: 'hint', text: location ? 'Punto marcado.' : 'Haz clic en el mapa para marcar el lugar.' });
    let picker = null;
    const locateBtn = el('button', { class: 'btn btn-outline btn-sm', type: 'button', text: 'Usar mi ubicación actual' });
    locateBtn.addEventListener('click', async () => {
      const done = busy(locateBtn, 'Buscando…');
      try { await picker.locate(); } catch (e) { toast(e.message, true); }
      done();
    });
    onMount(() => {
      picker = window.PetMap.picker(mapBox, location, (p) => {
        location = p;
        mapStatus.textContent = 'Punto marcado. Puedes arrastrar el marcador para ajustarlo.';
      });
    });

    const errorBox = el('p', { class: 'form-error full', role: 'alert', hidden: true });
    const progress = el('p', { class: 'progress', hidden: true });
    const submit = el('button', { type: 'submit', class: 'form-submit' },
      el('span', { class: 'spinner', 'aria-hidden': 'true' }),
      el('span', { class: 'btn-label', text: editing ? 'Guardar cambios' : 'Publicar reporte' }));

    // Mostrar u ocultar según el tipo y la mascota elegida.
    function syncPet() {
      const lost = !editing && typeLost.checked;
      petBox.hidden = !lost;
      const pet = pets.find((p) => p.id === petSel.value);
      petNameField.hidden = Boolean(pet);
      species.disabled = editing || Boolean(lost && pet);
      if (lost && pet) {
        species.value = pet.species;
        breed.value = pet.breed || '';
        color.value = pet.color || '';
        size.value = pet.size;
        features.value = pet.distinctive_features || '';
      }
      eventLabel.textContent = (editing ? report.type === 'lost' : lost) ? '¿Cuándo se perdió?' : '¿Cuándo la encontraste?';
      placeLabel.textContent = (editing ? report.type === 'lost' : lost) ? '¿Dónde se perdió? (referencia)' : '¿Dónde la encontraste? (referencia)';
    }
    const eventField = field('Fecha', eventAt);
    const eventLabel = eventField.querySelector('label');
    const placeField = field('Lugar', place);
    const placeLabel = placeField.querySelector('label');
    [typeLost, typeFound, petSel].forEach((x) => x.addEventListener('change', syncPet));

    const form = el('form', { novalidate: true },
      editing ? null : typeBox,
      editing ? null : petBox,
      el('div', { class: 'form-section-title', text: 'Descripción del animal' }),
      field('Especie', species),
      field('Raza', breed),
      field('Color', color),
      field('Tamaño', size),
      field('Rasgos particulares', features, { full: true }),
      el('div', { class: 'form-section-title', text: 'Cuándo y dónde' }),
      eventField,
      placeField,
      el('div', { class: 'full' },
        el('label', { text: 'Marca el lugar en el mapa' }),
        mapBox,
        el('div', { class: 'btn-row', style: 'margin-top:10px; justify-content:space-between;' }, mapStatus, locateBtn),
        el('span', { class: 'hint', text: 'Los demás verán solo una zona aproximada de ~1 km; el punto exacto es privado.' })),
      el('div', { class: 'form-section-title', text: 'Tu contacto (privado)' }),
      field('Teléfono', phone, { hint: 'Solo se comparte si se confirma una coincidencia.' }),
      field('Correo', email),
      editing ? null : el('div', { class: 'form-section-title', text: 'Fotos' }),
      editing ? null : field('Fotos del animal (1 a 5)', photos, { full: true, hint: 'Fotos claras del animal completo y de su cara ayudan a encontrar coincidencias. JPEG, PNG o WebP, máx. 10 MB cada una.' }),
      editing ? null : el('div', { class: 'full' }, previews),
      progress,
      errorBox,
      el('div', { class: 'full' }, submit));

    syncPet();

    function fail(message) {
      errorBox.textContent = message;
      errorBox.hidden = false;
      errorBox.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      errorBox.hidden = true;
      const lost = editing ? report.type === 'lost' : typeLost.checked;
      const files = editing ? [] : Array.from(photos.files);

      // Validación en el navegador (la API vuelve a validar todo).
      if (!color.value.trim()) return fail('Escribe el color del animal.');
      if (!eventAt.value) return fail('Indica la fecha.');
      if (new Date(eventAt.value) > new Date(Date.now() + 5 * 60000)) return fail('La fecha no puede estar en el futuro.');
      if (!location) return fail('Marca el lugar en el mapa.');
      if (phone.value.trim() && !/^[0-9+()\-\s]{7,40}$/.test(phone.value.trim())) return fail('El teléfono no es válido.');
      if (email.value.trim() && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.value.trim())) return fail('El correo no es válido.');
      if (!editing) {
        if (files.length < 1) return fail('Agrega al menos una foto del animal.');
        if (files.length > MAX_PHOTOS) return fail('Máximo ' + MAX_PHOTOS + ' fotos por reporte.');
        const problem = checkFiles(files);
        if (problem) return fail(problem);
      }

      const text = (input) => input.value.trim() || null;
      const desc = {
        breed: text(breed), color: color.value.trim(), size: size.value,
        distinctive_features: text(features),
        event_at: new Date(eventAt.value).toISOString(),
        location_label: text(place),
        lat: location.lat, lng: location.lng,
        contact_phone: text(phone), contact_email: text(email),
      };

      submit.disabled = true;
      submit.classList.add('is-loading');
      progress.hidden = false;
      const say = (t) => { progress.textContent = t; };
      let reportId = editing ? report.id : null;
      try {
        if (editing) {
          say('Guardando cambios…');
          await api('/api/reports/' + report.id, { method: 'PATCH', body: desc });
          toast('Cambios guardados');
          window.location.hash = '#reporte/' + report.id;
          return;
        }
        let petId = null;
        if (lost) {
          petId = petSel.value || null;
          if (!petId) {
            say('Registrando a tu mascota…');
            const pet = await api('/api/pets', { method: 'POST', body: {
              name: text(petName), species: species.value, breed: desc.breed, color: desc.color,
              size: desc.size, distinctive_features: desc.distinctive_features,
            } });
            petId = pet.id;
          }
        }
        say('Guardando el reporte…');
        const body = Object.assign({ type: lost ? 'lost' : 'found', species: species.value, pet_id: petId }, desc);
        Object.keys(body).forEach((k) => { if (body[k] === null) delete body[k]; });
        const created = await api('/api/reports', { method: 'POST', body });
        reportId = created.id;
        await uploadPhotos(reportId, files, say);
        say('Publicando…');
        await api('/api/reports/' + reportId + '/publish', { method: 'POST' });
        toast('¡Reporte publicado!');
        window.location.hash = '#reporte/' + reportId;
      } catch (err) {
        submit.disabled = false;
        submit.classList.remove('is-loading');
        progress.hidden = true;
        if (reportId && !editing) {
          // El reporte quedó guardado como borrador: se puede completar desde su página.
          toast('El reporte quedó como borrador. ' + err.message, true);
          window.location.hash = '#reporte/' + reportId;
        } else {
          fail(err.message);
        }
      }
    });

    return el('section', null,
      el('a', { class: 'back-link', href: editing ? '#reporte/' + report.id : '#mis-reportes', text: '← Volver' }),
      viewHead(editing ? 'Editar reporte' : 'Nuevo reporte',
        editing ? reportTitle(report) : 'Reportar una mascota',
        editing ? 'Las fotos se agregan o quitan desde la página del reporte.' : 'Completa los datos y sube fotos. Al publicar, buscaremos posibles coincidencias.'),
      el('div', { style: 'max-width:820px;' }, form));
  }

  // -------------------------------------------------------------------------
  // Navegación
  // -------------------------------------------------------------------------
  const UUID = '([0-9a-fA-F-]{36})';
  const routes = [
    [/^explorar$/, () => viewExplore()],
    [/^mis-reportes$/, () => viewMine()],
    [/^nuevo(?:\/(lost|found))?$/, (m) => viewForm({ type: m[1] })],
    [new RegExp('^editar/' + UUID + '$'), (m) => viewForm({ editId: m[1] })],
    [new RegExp('^reporte/' + UUID + '$'), (m) => viewReport(m[1])],
    [new RegExp('^coincidencia/' + UUID + '$'), (m) => viewMatch(m[1])],
    [/^notificaciones$/, () => viewNotifications()],
  ];

  function setActiveNav(name) {
    document.querySelectorAll('[data-nav]').forEach((a) => a.classList.toggle('is-active', a.dataset.nav === name));
  }

  function closeMenu() {
    $('#nav-links').classList.remove('open');
    $('#burger').classList.remove('open');
    $('#burger').setAttribute('aria-expanded', 'false');
  }

  async function route() {
    const hash = window.location.hash.replace(/^#/, '') || 'explorar';
    const token = ++renderToken;
    const view = $('#view');
    mounted = [];
    setActiveNav(hash.split('/')[0]);
    closeMenu();
    const found = routes.find(([re]) => re.test(hash));
    if (!found) { window.location.hash = '#explorar'; return; }
    view.replaceChildren(el('p', { class: 'muted', text: 'Cargando…' }));
    try {
      const content = await found[1](hash.match(found[0]));
      if (token !== renderToken) return; // el usuario ya cambió de vista
      view.replaceChildren(content);
      const pending = mounted;
      mounted = [];
      pending.forEach((fn) => fn());
    } catch (err) {
      if (token !== renderToken) return;
      if (err.status === 401) { await signOut(); return; }
      view.replaceChildren(
        el('div', { class: 'empty' },
          el('p', { text: err.status === 404 ? 'No encontramos lo que buscas (o no tienes acceso).' : err.message }),
          el('a', { class: 'btn btn-outline', href: '#explorar', text: 'Ir a Explorar' })));
    }
  }

  // -------------------------------------------------------------------------
  // Sesión
  // -------------------------------------------------------------------------
  function show(viewId) {
    ['loading-view', 'auth-view', 'app-view'].forEach((id) => { $('#' + id).hidden = id !== viewId; });
    const inApp = viewId === 'app-view';
    $('#nav-links').hidden = !inApp;
    $('#burger').hidden = !inApp;
    $('#nav-new').hidden = !inApp;
  }

  async function signOut() {
    try { const client = await getClient(); await client.auth.signOut(); } catch (e) { /* ignorar */ }
    clearInterval(badgeTimer);
    me = null;
    show('auth-view');
  }

  let appStarted = false;
  async function enterApp() {
    try {
      [me, speciesList] = await Promise.all([api('/api/me'), api('/api/species')]);
    } catch (err) {
      if (err.status === 401) { await signOut(); return; }
      show('loading-view');
      $('#loading-view .muted').textContent = 'No se pudo cargar la aplicación: ' + err.message;
      return;
    }
    // El teléfono del registro (si lo hubo) se guarda en el perfil al primer inicio de sesión.
    if (!me.phone) {
      const session = await getSession();
      const phone = session && session.user && session.user.user_metadata && session.user.user_metadata.phone;
      if (phone) { try { me = await api('/api/me', { method: 'PATCH', body: { phone } }); } catch (e) { /* opcional */ } }
    }
    show('app-view');
    if (!appStarted) {
      appStarted = true;
      window.addEventListener('hashchange', route);
    }
    route();
    refreshBadge();
    clearInterval(badgeTimer);
    badgeTimer = setInterval(refreshBadge, 60000);
  }

  function setupLogin() {
    const form = $('#login-form');
    const errorBox = $('#login-error');
    const btn = form.querySelector('.form-submit');
    const label = btn.querySelector('.btn-label');
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      errorBox.hidden = true;
      const emailValue = $('#login-email').value.trim();
      const password = $('#login-password').value;
      if (!emailValue || !password) { errorBox.textContent = 'Escribe tu correo y tu contraseña.'; errorBox.hidden = false; return; }
      btn.disabled = true; btn.classList.add('is-loading'); label.textContent = 'Entrando…';
      try {
        const client = await getClient();
        const { error } = await client.auth.signInWithPassword({ email: emailValue, password });
        if (error) throw error;
        $('#login-password').value = '';
        await enterApp();
      } catch (err) {
        errorBox.textContent = authMessage(err);
        errorBox.hidden = false;
      } finally {
        btn.disabled = false; btn.classList.remove('is-loading'); label.textContent = 'Entrar';
      }
    });
  }

  function setupMenu() {
    const burger = $('#burger');
    const links = $('#nav-links');
    burger.addEventListener('click', () => {
      const open = links.classList.toggle('open');
      burger.classList.toggle('open', open);
      burger.setAttribute('aria-expanded', String(open));
    });
    $('#logout').addEventListener('click', async () => {
      await signOut();
      window.location.href = 'index.html';
    });
  }

  async function start() {
    setupMenu();
    setupLogin();
    let client;
    try {
      client = await getClient();
    } catch (err) {
      $('#loading-view .muted').textContent = 'No se pudo conectar con el servidor. ¿Está encendido el backend?';
      return;
    }
    client.auth.onAuthStateChange((event) => {
      if (event === 'SIGNED_OUT') show('auth-view');
    });
    const session = await getSession();
    if (session) await enterApp();
    else show('auth-view');
  }

  start();
})();
