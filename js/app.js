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

  function toast(message, isError, ms) {
    const box = $('#toast');
    box.textContent = message;
    box.classList.toggle('is-error', Boolean(isError));
    box.hidden = false;
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => { box.hidden = true; }, ms || (isError ? 6000 : 3500));
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
  const MATCH_STATUS = { suggested: 'Posible coincidencia', requested: 'Esperando respuesta', confirmed: 'Confirmada', discarded: 'Descartada' };
  // Texto de cada aviso según quién lo recibe (n.my_role) y la especie (n.species).
  function notifText(n) {
    const animal = n.species === 'cat' ? 'un gato' : n.species === 'dog' ? 'un perro' : 'una mascota';
    if (n.kind === 'new_match') {
      return n.my_role === 'found_owner'
        ? 'El animal que encontraste se parece a ' + animal + ' reportado como perdido'
        : '¡Posible coincidencia! Encontraron ' + animal + ' que se parece a tu mascota';
    }
    if (n.kind === 'match_requested') return 'El dueño de ' + animal + ' perdido dice que el animal que encontraste es suyo';
    if (n.kind === 'match_accepted') return 'Quien encontró la mascota aceptó tu solicitud: ya puedes ver su teléfono';
    if (n.kind === 'match_confirmed') return 'El dueño confirmó que es su mascota: ya puedes ver su contacto';
    if (n.kind === 'match_discarded') return 'Una posible coincidencia fue descartada';
    if (n.kind === 'new_comment') return 'Nuevo comentario en tu reporte';
    return 'Aviso';
  }
  function notifHint(n) {
    if (n.kind === 'new_match') {
      return n.my_role === 'found_owner'
        ? 'Si el dueño pide tu contacto, te avisaremos para que aceptes o no.'
        : 'Compara las fotos. Si es tu mascota, pulsa "Es mi mascota" para pedir el contacto de quien la encontró.';
    }
    if (n.kind === 'match_requested') return 'Revisa su seña y sus fotos, y acepta o rechaza. Tu teléfono solo se comparte si aceptas.';
    if (n.kind === 'new_comment') return 'Alguien de la comunidad escribió en tu reporte.';
    return '';
  }
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

  // Vista "lista": una publicación por fila, como en las redes sociales del celular.
  function reportPost(r) {
    return el('a', { class: 'report-post', href: '#reporte/' + r.id },
      el('div', { class: 'post-head' },
        el('span', { class: 'post-avatar post-avatar-' + r.type, 'aria-hidden': 'true', text: r.type === 'lost' ? '!' : '✓' }),
        el('div', { class: 'post-head-text' },
          el('strong', { text: reportTitle(r) }),
          el('small', { text: (r.location_label || 'Ubicación en el mapa') + ' · ' + fmtDate(r.event_at) })),
        el('div', { class: 'badges' }, badge(r.type, TYPE[r.type]), r.is_mine ? badge(r.status, STATUS[r.status]) : null)),
      photoImg(firstPhoto(r), 'post-photo', 'Foto de ' + reportTitle(r)),
      el('div', { class: 'post-body' },
        el('p', { class: 'post-facts', text: [r.color, SIZE[r.size], r.breed].filter(Boolean).join(' · ') || speciesName(r.species) }),
        r.distinctive_features ? el('p', { class: 'post-text', text: r.distinctive_features }) : null,
        el('span', { class: 'post-cta', text: 'Ver reporte →' })));
  }

  // Cuadrícula o lista: la elección se recuerda en este navegador (si no se puede, cuadrícula).
  const LAYOUT_KEY = 'petalert.vista';
  function getLayout() {
    try { return localStorage.getItem(LAYOUT_KEY) === 'list' ? 'list' : 'grid'; } catch (e) { return 'grid'; }
  }
  function setLayout(mode) { try { localStorage.setItem(LAYOUT_KEY, mode); } catch (e) { /* opcional */ } }

  // Contenedor de reportes que se puede cambiar entre cuadrícula y lista sin volver a pedirlos.
  function reportCollection() {
    const rows = [];
    let mode = getLayout();
    const box = el('div');
    const item = (r) => (mode === 'list' ? reportPost(r) : reportCard(r));
    const paint = () => { box.className = mode === 'list' ? 'card-feed' : 'card-grid'; box.replaceChildren(...rows.map(item)); };
    const buttons = [['grid', 'Cuadrícula', '▦'], ['list', 'Lista', '☰']].map(([value, label, icon]) =>
      el('button', { type: 'button', class: 'layout-btn', 'data-layout': value, 'aria-pressed': String(mode === value), title: 'Ver en ' + label.toLowerCase(),
        onclick: () => {
          mode = value; setLayout(value);
          buttons.forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.layout === value)));
          paint();
        } }, el('span', { 'aria-hidden': 'true', text: icon }), ' ' + label));
    const toggle = el('div', { class: 'layout-toggle', role: 'group', 'aria-label': 'Forma de ver los reportes' }, buttons);
    paint();
    return {
      box, toggle,
      add(list) { rows.push(...list); box.append(...list.map(item)); },
      clear() { rows.length = 0; box.replaceChildren(); },
      get size() { return rows.length; },
    };
  }

  // -------------------------------------------------------------------------
  // Vista: explorar reportes activos
  // -------------------------------------------------------------------------
  async function viewExplore() {
    const state = { offset: 0 };
    const reports = reportCollection();
    const emptyHolder = el('div');
    const typeSel = selectEl('f-type', [['', 'Perdidas y encontradas'], ['lost', 'Mascotas perdidas'], ['found', 'Mascotas encontradas']]);
    const spSel = selectEl('f-species', [['', 'Todas las especies'], ...speciesList.map((s) => [s.code, s.name_es])]);
    typeSel.setAttribute('aria-label', 'Filtrar por tipo');
    spSel.setAttribute('aria-label', 'Filtrar por especie');
    const more = el('button', { class: 'btn btn-outline', type: 'button', hidden: true, text: 'Ver más' });

    async function load(reset) {
      if (reset) { state.offset = 0; reports.clear(); emptyHolder.replaceChildren(); }
      const params = new URLSearchParams({ limit: PAGE_SIZE, offset: state.offset });
      if (typeSel.value) params.set('type', typeSel.value);
      if (spSel.value) params.set('species', spSel.value);
      const rows = await api('/api/reports?' + params);
      reports.add(rows);
      state.offset += rows.length;
      more.hidden = rows.length < PAGE_SIZE;
      if (!reports.size) {
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
      el('div', { class: 'filters' }, typeSel, spSel, reports.toggle),
      reports.box, emptyHolder,
      el('div', { class: 'btn-row', style: 'justify-content:center; margin-top:24px;' }, more));
  }

  // -------------------------------------------------------------------------
  // Vista: mis reportes
  // -------------------------------------------------------------------------
  async function viewMine() {
    const rows = await api('/api/reports/mine');
    const newBtn = el('a', { class: 'btn btn-coral', href: '#nuevo', text: '+ Nuevo reporte' });
    const reports = reportCollection();
    reports.add(rows);
    return el('section', null,
      viewHead('Mis reportes', 'Tus reportes', 'Aquí ves todos tus reportes (también borradores y cerrados) y sus posibles coincidencias.', newBtn),
      rows.length
        ? el('div', null, el('div', { class: 'filters' }, reports.toggle), reports.box)
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
      el('div', { class: 'panel' }, el('h3', { text: 'Datos' }), facts),
      // Difundir en redes: solo reportes publicados (cualquiera con sesión puede ayudar).
      r.status === 'active' && window.PetShare ? el('div', { class: 'panel', id: 'share-panel' },
        el('h3', { text: 'Ayuda a difundir' }),
        window.PetShare.panel({ report: r, photoUrl: ready[0] ? () => photoUrl(ready[0].id) : null,
          onCopied: () => toast('Texto copiado') }),
        el('p', { class: 'share-note', text: 'El texto no incluye teléfonos, correos ni el punto exacto del mapa.' })) : null);

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
    } else if (r.status === 'active' && r.type === 'found') {
      // Reporte encontrado de otra persona: "Es mi mascota" (con filtros y advertencia).
      const mine = (await api('/api/reports/mine')).filter((x) => x.type === 'lost' && x.status === 'active' && x.species === r.species);
      const panel = el('div', { class: 'panel' }, el('h3', { text: '¿Es tu mascota?' }));
      if (mine.length) {
        panel.append(
          el('p', { class: 'hint', style: 'margin:-6px 0 12px;', text: 'Por seguridad, el contacto de quien la encontró no se publica. Pídelo con "Es mi mascota": escribirás una seña que solo tú conoces y quien la encontró la revisará.' }),
          el('button', { class: 'btn btn-coral', type: 'button', text: 'Es mi mascota', onclick: async (e) => {
            const btn = e.currentTarget;
            const answer = await claimDialog({ lostReports: mine });
            if (!answer) return;
            const done = busy(btn, 'Enviando…');
            try {
              afterRequest(await api('/api/reports/' + r.id + '/claim', { method: 'POST', body: { note: answer.note, lost_report_id: answer.lostReportId } }));
            } catch (err) { done(); toast(err.message, true, 9000); }
          } }));
      } else {
        panel.append(
          el('p', { class: 'hint', style: 'margin:-6px 0 12px;', text: 'Por seguridad, el contacto de quien la encontró no se publica. Para pedirlo:' }),
          el('ol', { class: 'steps-list' },
            el('li', { text: 'Publica un reporte de tu ' + speciesName(r.species).toLowerCase() + ' perdido con una foto tuya (no copies la de este reporte).' }),
            el('li', { text: 'Vuelve aquí y pulsa "Es mi mascota", o espera el aviso si PetAlert encuentra el parecido.' }),
            el('li', { text: 'Quien la encontró revisa tu seña y acepta; entonces verás su teléfono.' })),
          el('div', { class: 'btn-row', style: 'margin-top:12px;' },
            el('a', { class: 'btn btn-coral', href: '#nuevo/lost', text: 'Reportar mi mascota perdida' })));
      }
      right.append(panel);
    } else if (r.status === 'active') {
      right.append(el('div', { class: 'panel' },
        el('h3', { text: '¿Viste a esta mascota?' }),
        el('p', { class: 'hint', style: 'margin:-6px 0 12px;', text: 'Cuéntalo en los comentarios o publica un reporte de mascota encontrada con una foto: PetAlert le avisará al dueño.' }),
        el('a', { class: 'btn btn-coral', href: '#nuevo/found', text: 'Reportar que la encontré' })));
    }

    if (r.status === 'active' || (r.is_mine && r.status !== 'draft')) right.append(await commentsPanel(r));

    return el('section', null,
      el('a', { class: 'back-link', href: r.is_mine ? '#mis-reportes' : '#explorar', text: '← Volver' }),
      viewHead(r.is_mine ? 'Mi reporte' : 'Reporte', reportTitle(r)),
      el('div', { class: 'detail-grid' }, left, right));
  }

  // -------------------------------------------------------------------------
  // Comentarios de un reporte (sin correos ni enlaces de chat: la base los rechaza; teléfonos sí)
  // -------------------------------------------------------------------------
  async function commentsPanel(r) {
    const list = el('div', { class: 'comment-list' });
    const canWrite = r.status === 'active';
    async function load() {
      const rows = await api('/api/reports/' + r.id + '/comments');
      list.replaceChildren(...rows.map((c) => el('div', { class: 'comment' },
        el('div', { class: 'comment-head' },
          el('strong', { text: c.author }),
          c.is_report_owner ? el('span', { class: 'badge badge-active', text: 'Autor del reporte' }) : null,
          el('small', { text: fmtDate(c.created_at) }),
          c.can_delete ? el('button', { class: 'link comment-delete', type: 'button', text: 'Borrar', onclick: async () => {
            if (!confirm('¿Borrar este comentario?')) return;
            try { await api('/api/comments/' + c.id, { method: 'DELETE' }); await load(); } catch (err) { toast(err.message, true); }
          } }) : null),
        el('p', { text: c.body }))));
      if (!rows.length) list.append(el('p', { class: 'muted', text: canWrite ? 'Aún no hay comentarios. ¿Viste algo? Cuéntalo aquí.' : 'No hay comentarios.' }));
    }
    let form = null;
    if (canWrite) {
      const text = el('textarea', { id: 'comment-body', rows: 2, maxlength: 500, placeholder: 'Ej.: lo vi ayer cerca del parque, iba con un collar azul' });
      const send = el('button', { class: 'btn btn-primary btn-sm', type: 'submit', text: 'Comentar' });
      form = el('form', { class: 'comment-form' },
        el('label', { for: 'comment-body', class: 'sr-only', text: 'Escribe un comentario' }), text,
        el('p', { class: 'hint', text: 'Los comentarios los ve cualquier persona con cuenta. Si escribes un teléfono, será público. No se permiten correos ni enlaces de chat.' }),
        el('div', { class: 'btn-row', style: 'justify-content:flex-end;' }, send));
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (text.value.trim().length < 2) { text.focus(); return; }
        const done = busy(send, 'Enviando…');
        try { await api('/api/reports/' + r.id + '/comments', { method: 'POST', body: { body: text.value.trim() } }); text.value = ''; await load(); } catch (err) { toast(err.message, true, 9000); }
        done();
      });
    }
    try { await load(); } catch (err) { list.append(el('p', { class: 'muted', text: 'No se pudieron cargar los comentarios.' })); }
    return el('div', { class: 'panel', id: 'comments-panel' }, el('h3', { text: 'Comentarios' }), list, form);
  }

  // -------------------------------------------------------------------------
  // "Es mi mascota": advertencia + seña obligatoria (decisión de Daniela, 2026-11-18)
  // -------------------------------------------------------------------------
  // opts.lostReports: si viene de Explorar, la persona elige cuál de sus reportes perdidos es.
  // Devuelve { note, lostReportId } o null si cancela.
  function claimDialog(opts) {
    const o = opts || {};
    return new Promise((resolve) => {
      const note = el('textarea', { id: 'claim-note', rows: 3, maxlength: 300,
        placeholder: 'Ej.: collar rojo con placa, cicatriz en la oreja izquierda, responde a "Toby"' });
      const pick = o.lostReports && o.lostReports.length > 1
        ? selectEl('claim-lost', o.lostReports.map((r) => [r.id, reportTitle(r) + ' · ' + ([r.color, r.location_label].filter(Boolean).join(' · ') || fmtDate(r.event_at))]))
        : null;
      const error = el('p', { class: 'form-error', role: 'alert', hidden: true });
      const cancel = el('button', { class: 'btn btn-outline', type: 'button', text: 'Cancelar' });
      const send = el('button', { class: 'btn btn-coral', type: 'submit', text: 'Enviar solicitud' });
      const form = el('form', { method: 'dialog', class: 'modal-body' },
        el('h3', { id: 'claim-title', text: '¿Es tu mascota?' }),
        el('div', { class: 'modal-warning' },
          el('strong', { text: 'Antes de continuar, lee esto:' }),
          el('ul', null,
            el('li', { text: 'Pide el contacto solo si de verdad crees que es tu mascota. Reclamar animales ajenos para obtener datos de otras personas es un mal uso de PetAlert y queda registrado con tu cuenta.' }),
            el('li', { text: 'Quien la encontró verá tu seña y las fotos de tu reporte para comprobar que eres el dueño.' }),
            el('li', { text: 'Si tiene cuenta, debe aceptar: mientras tanto solo verás su correo. Si reportó sin cuenta, verás su teléfono al enviar.' }),
            el('li', { text: 'Puedes hacer máximo 3 solicitudes y ver máximo 3 teléfonos cada 24 horas.' }))),
        pick ? field('¿Cuál de tus mascotas perdidas es?', pick) : null,
        field('Seña particular que solo tú conoces', note, { hint: 'Entre 8 y 300 caracteres. No escribas tu teléfono aquí.' }),
        error,
        el('div', { class: 'btn-row', style: 'justify-content:flex-end; margin-top:14px;' }, cancel, send));
      const dlg = el('dialog', { class: 'modal', 'aria-labelledby': 'claim-title' }, form);
      let answer = null;
      cancel.addEventListener('click', () => dlg.close());
      form.addEventListener('submit', (e) => {
        const text = note.value.trim();
        if (text.length < 8) {
          e.preventDefault();
          error.textContent = 'Escribe una seña de al menos 8 caracteres.';
          error.hidden = false;
          note.focus();
          return;
        }
        answer = { note: text, lostReportId: pick ? pick.value : (o.lostReports && o.lostReports[0] && o.lostReports[0].id) };
      });
      dlg.addEventListener('close', () => { dlg.remove(); resolve(answer); });
      document.body.append(dlg);
      dlg.showModal();
      note.focus();
    });
  }

  function afterRequest(m) {
    toast(m.status === 'confirmed'
      ? 'Listo: ya puedes ver el contacto de quien la encontró.'
      : 'Solicitud enviada. Mientras quien la encontró acepta, puedes escribirle a su correo.', false, 8000);
    location.hash = '#coincidencia/' + m.id;
    route();
  }

  // -------------------------------------------------------------------------
  // Coincidencias
  // -------------------------------------------------------------------------
  function matchActions(m) {
    const row = el('div', { class: 'btn-row' });
    if (m.can_request) {
      row.append(el('button', { class: 'btn btn-primary btn-sm', type: 'button', text: 'Es mi mascota', onclick: async (e) => {
        const btn = e.currentTarget;
        const answer = await claimDialog();
        if (!answer) return;
        const done = busy(btn, 'Enviando…');
        try { afterRequest(await api('/api/matches/' + m.id + '/request', { method: 'POST', body: { note: answer.note } })); } catch (err) { done(); toast(err.message, true, 9000); }
      } }));
    }
    if (m.can_answer) {
      row.append(el('button', { class: 'btn btn-primary btn-sm', type: 'button', text: 'Sí, es su mascota', onclick: async (e) => {
        if (!confirm('¿Aceptas que es su mascota?\n\nSe compartirán los contactos entre las dos personas y ambos reportes quedarán resueltos.')) return;
        const done = busy(e.currentTarget, 'Aceptando…');
        try { await api('/api/matches/' + m.id + '/answer', { method: 'POST', body: { accept: true } }); toast('Aceptado: ya pueden contactarse'); route(); } catch (err) { done(); toast(err.message, true); }
      } }));
      row.append(el('button', { class: 'btn btn-danger btn-sm', type: 'button', text: 'No es su mascota', onclick: async (e) => {
        if (!confirm('¿Rechazar la solicitud? No se compartirá tu teléfono.')) return;
        const done = busy(e.currentTarget, 'Rechazando…');
        try { await api('/api/matches/' + m.id + '/answer', { method: 'POST', body: { accept: false } }); toast('Solicitud rechazada'); route(); } catch (err) { done(); toast(err.message, true); }
      } }));
    }
    if (m.can_discard) {
      const cancelling = m.status === 'requested';
      row.append(el('button', { class: 'btn btn-danger btn-sm', type: 'button', text: cancelling ? 'Cancelar solicitud' : 'No es', onclick: async (e) => {
        if (!confirm(cancelling ? '¿Cancelar tu solicitud de contacto?' : '¿Descartar esta posible coincidencia? No volverá a sugerirse.')) return;
        const done = busy(e.currentTarget, 'Descartando…');
        try { await api('/api/matches/' + m.id + '/discard', { method: 'POST' }); toast(cancelling ? 'Solicitud cancelada' : 'Coincidencia descartada'); route(); } catch (err) { done(); toast(err.message, true); }
      } }));
    }
    return row;
  }

  const scoreText = (m) => (m.visual_score === null || m.visual_score === undefined
    ? (m.origin === 'claim' ? 'Pedida por el dueño' : 'Sin puntaje') : 'Parecido ' + pct(m.visual_score));

  function matchItem(m) {
    const o = m.other_report;
    return el('div', { class: 'match-item' },
      photoImg(firstPhoto(o), 'thumb', 'Foto del otro reporte'),
      el('div', null,
        el('div', { class: 'badges', style: 'margin-bottom:6px;' }, badge(m.status, MATCH_STATUS[m.status])),
        el('p', null, el('span', { class: 'score', text: scoreText(m) }), ' · a ' + km(m.distance_km)),
        el('p', { class: 'muted', text: [speciesName(o.species), o.color, SIZE[o.size]].filter(Boolean).join(' · ') + ' · ' + fmtDate(o.event_at) }),
        el('div', { class: 'btn-row', style: 'margin-top:10px;' },
          el('a', { class: 'btn btn-outline btn-sm', href: '#coincidencia/' + m.id, text: 'Ver detalle' }),
          matchActions(m))));
  }

  // Recuadro de contacto de una coincidencia confirmada. El teléfono se pide con un botón (límite 3/24 h).
  function contactBox(m) {
    const c = m.contact;
    const rows = el('dl', { class: 'facts', style: 'margin-top:8px;' },
      el('dt', { text: 'Nombre' }), el('dd', { text: c.display_name || '—' }),
      el('dt', { text: 'Correo' }), el('dd', { text: c.email || '—' }));
    const links = el('div', { class: 'btn-row', style: 'margin-top:10px;' });
    if (c.phone) {
      const digits = c.phone.replace(/\D/g, '');
      // Celular colombiano sin indicativo (10 dígitos que empiezan por 3) → se agrega el 57.
      const wa = digits.length === 10 && digits[0] === '3' ? '57' + digits : digits;
      rows.append(el('dt', { text: 'Teléfono' }), el('dd', { text: c.phone }));
      links.append(
        el('a', { class: 'btn btn-primary btn-sm', href: 'tel:+' + wa, text: 'Llamar' }),
        el('a', { class: 'btn btn-primary btn-sm', href: 'https://wa.me/' + wa, target: '_blank', rel: 'noopener', text: 'WhatsApp' }));
    } else if (c.has_phone) {
      links.append(el('button', { class: 'btn btn-primary btn-sm', type: 'button', text: 'Ver teléfono', onclick: async (e) => {
        const done = busy(e.currentTarget, 'Cargando…');
        try { await api('/api/matches/' + m.id + '/phone', { method: 'POST' }); route(); } catch (err) { done(); toast(err.message, true, 10000); }
      } }));
    }
    if (c.email) links.append(el('a', { class: 'btn btn-outline btn-sm', href: 'mailto:' + c.email, text: 'Enviar correo' }));
    return el('div', { class: 'contact-box' },
      el('strong', { text: m.my_role === 'lost_owner' ? 'Contacto de quien encontró a tu mascota' : 'Contacto del dueño de la mascota' }),
      rows, links,
      !c.phone && c.has_phone ? el('p', { class: 'hint', style: 'margin-top:8px;', text: 'Por seguridad, cada persona puede ver máximo 3 teléfonos cada 24 horas. Hoy te quedan ' + c.phone_views_left + '.' }) : null,
      el('p', { class: 'hint', style: 'margin-top:10px;', text: 'Acuerden un lugar público para el encuentro y pide fotos o detalles que solo el dueño conozca.' }));
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

    const owner = m.my_role === 'lost_owner';
    const sena = m.claim_note ? el('div', { class: 'notice', style: 'margin-bottom:12px;' },
      el('strong', { text: owner ? 'Tu seña: ' : 'Seña que escribió el dueño: ' }), m.claim_note) : null;
    let contact;
    if (m.status === 'confirmed' && m.contact) {
      contact = contactBox(m);
    } else if (m.status === 'requested' && owner) {
      const c = m.contact || {};
      contact = el('div', { class: 'contact-box' },
        el('strong', { text: 'Solicitud enviada' }),
        el('p', { style: 'margin-top:6px;', text: 'Quien la encontró debe aceptar para que veas su teléfono. Te avisaremos en "Avisos".' }),
        c.email
          ? el('p', { style: 'margin-top:6px;' }, 'Mientras tanto puedes escribirle: ', el('a', { class: 'link', href: 'mailto:' + c.email, text: c.email }))
          : el('p', { class: 'muted', style: 'margin-top:6px;', text: 'Esta persona no dejó correo; espera a que acepte.' }));
    } else if (m.status === 'requested') {
      contact = el('p', { text: 'La persona que perdió esta mascota dice que es suya. Compara sus fotos y su seña. Si aceptas, verás su contacto y ella podrá ver tu teléfono; si no, no se comparte nada.' });
    } else if (m.status === 'suggested') {
      contact = el('p', { class: 'muted', text: m.can_request
        ? 'Si reconoces a tu mascota, pulsa "Es mi mascota". Escribirás una seña que solo tú conoces y quien la encontró la verá.'
        : 'Si el dueño pide tu contacto, te avisaremos para que decidas si aceptas. Tu teléfono no se comparte sin tu permiso.' });
    } else {
      contact = el('p', { class: 'muted', text: 'Esta coincidencia fue descartada.' });
    }

    return el('section', null,
      el('a', { class: 'back-link', href: '#reporte/' + m.my_report_id, text: '← Volver a mi reporte' }),
      viewHead('Coincidencia', MATCH_STATUS[m.status]),
      el('p', { class: 'notice', style: 'margin-bottom:20px;', text: m.origin === 'claim'
        ? 'El dueño de la mascota perdida señaló este reporte. No es una confirmación: compara bien las fotos, los rasgos y la seña.'
        : 'El sistema sugiere que podría tratarse del mismo animal por el parecido de las fotos y la cercanía. No es una confirmación: compara bien las fotos y los rasgos.' }),
      el('div', { class: 'detail-grid' },
        el('div', null,
          el('div', { class: 'panel' },
            el('h3', { text: o.type === 'lost' ? 'Mascota perdida (de la otra persona)' : 'Mascota encontrada (por la otra persona)' }),
            photos.length ? el('div', { class: 'photo-grid' }, photos.map((p, i) => photoImg(p.id, 'thumb', 'Foto ' + (i + 1)))) : el('p', { class: 'muted', text: 'Sin fotos disponibles.' })),
          el('div', { class: 'panel' }, el('h3', { text: 'Datos' }), facts)),
        el('div', null,
          el('div', { class: 'panel' }, el('h3', { text: 'Contacto' }), sena, contact,
            el('div', { style: 'margin-top:14px;' }, matchActions(m))),
          el('div', { class: 'panel' },
            el('h3', { text: m.origin === 'claim' ? 'Datos de la solicitud' : 'Por qué se sugiere' }),
            el('dl', { class: 'facts' },
              el('dt', { text: 'Parecido de fotos' }), el('dd', { text: m.visual_score === null ? '—' : pct(m.visual_score) }),
              el('dt', { text: 'Distancia aprox.' }), el('dd', { text: km(m.distance_km) }),
              el('dt', { text: 'Puntaje total' }), el('dd', { text: m.total_score === null ? '—' : pct(m.total_score) }))),
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
        location.hash = n.match_id ? '#coincidencia/' + n.match_id : '#reporte/' + n.report_id;
      },
    }, el('span', null, el('strong', { text: notifText(n) }), el('br'),
      notifHint(n) ? el('span', { class: 'muted', text: notifHint(n) }) : null, notifHint(n) ? el('br') : null,
      el('small', { text: fmtDate(n.created_at) })),
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
      // Si llegaron avisos nuevos (o al entrar hay sin leer), se dice en pantalla, no solo en el contador.
      const newest = unread[0] && unread[0].id;
      if (newest && newest !== refreshBadge.lastSeen && location.hash !== '#notificaciones') {
        toast(unread.length === 1
          ? notifText(unread[0]) + '. Ábrelo en "Avisos".'
          : 'Tienes ' + unread.length + ' avisos nuevos de posibles coincidencias. Ábrelos en "Avisos".', false, 10000);
      }
      refreshBadge.lastSeen = newest || null;
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
    let saveDraft = () => {};  // se define abajo (solo para reportes nuevos)
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
        saveDraft();
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

    // Borrador de un reporte NUEVO en esta pestaña (sessionStorage). En el celular, elegir fotos
    // abre la cámara y el navegador puede recargar la página al volver; así no se pierde lo escrito.
    // Las fotos no se guardan: se vuelven a elegir.
    const DRAFT_KEY = 'petalert.borrador.reporte';
    const textFields = { breed, color, features, eventAt, place, phone, email, petName };
    let restoredNotice = null;
    if (!editing) {
      let d = null;
      try { d = JSON.parse(sessionStorage.getItem(DRAFT_KEY)); } catch (e) { d = null; }
      if (d && d.type === (typeFound.checked ? 'found' : 'lost')) {
        if (pets.some((p) => p.id === d.pet)) petSel.value = d.pet;
        if (speciesList.some((s) => s.code === d.species)) species.value = d.species;
        if (['small', 'medium', 'large'].includes(d.size)) size.value = d.size;
        syncPet();
        Object.entries(textFields).forEach(([k, input]) => { if (typeof d[k] === 'string') input.value = d[k]; });
        if (d.location && Number.isFinite(d.location.lat) && Number.isFinite(d.location.lng)) {
          location = { lat: d.location.lat, lng: d.location.lng };
          mapStatus.textContent = 'Punto marcado.';
        }
        restoredNotice = el('div', { class: 'notice', style: 'margin-bottom:16px; display:flex; flex-wrap:wrap; gap:8px 14px; align-items:center;' },
          el('span', { text: 'Recuperamos lo que habías escrito. Vuelve a elegir las fotos.' }),
          el('button', { class: 'link', type: 'button', style: 'background:none; border:0; padding:0; font:inherit; cursor:pointer;', text: 'Empezar de nuevo', onclick: () => {
            try { sessionStorage.removeItem(DRAFT_KEY); } catch (e) { /* nada */ }
            route();
          } }));
      }
      saveDraft = () => {
        const data = { type: typeFound.checked ? 'found' : 'lost', pet: petSel.value, species: species.value, size: size.value, location };
        Object.entries(textFields).forEach(([k, input]) => { data[k] = input.value; });
        try { sessionStorage.setItem(DRAFT_KEY, JSON.stringify(data)); } catch (e) { /* sin almacenamiento */ }
      };
      form.addEventListener('input', saveDraft);
      form.addEventListener('change', saveDraft);
    }

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
        try { sessionStorage.removeItem(DRAFT_KEY); } catch (e) { /* nada */ }  // ya quedó guardado
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
      el('div', { style: 'max-width:820px;' }, restoredNotice, form));
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
    // Un invitado (reporte rápido sin cuenta) no usa la app: debe iniciar sesión o crear cuenta.
    // signInWithPassword reemplaza la sesión de invitado.
    if (session && !window.PetAlert.isAnonymous(session)) await enterApp();
    else show('auth-view');
  }

  start();
})();
