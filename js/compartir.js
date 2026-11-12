// PET Alert · Botones para difundir un reporte en redes (WhatsApp, Facebook, menú del celular).
//
// Privacidad: el texto solo lleva datos públicos del reporte (especie, color, tamaño, fecha y
// el lugar que la persona escribió). NUNCA el teléfono, el correo ni el punto exacto del mapa.
// El enlace lleva a la página principal (los reportes requieren sesión, decisión D1).
(function () {
  'use strict';

  const SIZE = { small: 'pequeño', medium: 'mediano', large: 'grande' };
  const SPECIES = { dog: 'perro', cat: 'gato' };

  function shareText(report) {
    const animal = SPECIES[report.species] || 'mascota';
    const article = SPECIES[report.species] ? 'un ' : 'una ';
    const traits = [report.color, SIZE[report.size], report.breed].filter(Boolean).join(', ');
    const when = report.event_at
      ? new Date(report.event_at).toLocaleDateString('es-CO', { day: 'numeric', month: 'long' }) : '';
    const place = report.location_label ? ' cerca de ' + report.location_label : '';
    const site = window.location.origin;
    if (report.type === 'lost') {
      return 'Se busca ' + article + animal + (traits ? ' (' + traits + ')' : '') + '. Se perdió' +
        (when ? ' el ' + when : '') + place + '. Si lo ves, repórtalo en PetAlert IA: ' + site + '/#encontre';
    }
    return 'Se encontró ' + article + animal + (traits ? ' (' + traits + ')' : '') + (when ? ' el ' + when : '') + place +
      '. Si es tuyo o sabes de quién es, búscalo en PetAlert IA: ' + site + '/';
  }

  function button(cls, label, onClick, href) {
    const node = document.createElement(href ? 'a' : 'button');
    node.className = 'share-btn ' + cls;
    node.textContent = label;
    if (href) { node.href = href; node.target = '_blank'; node.rel = 'noopener'; } else { node.type = 'button'; }
    if (onClick) node.addEventListener('click', onClick);
    return node;
  }

  // panel({ report, photoFile?: File, photoUrl?: () => Promise<string>, onCopied?: () => void })
  // → elemento con los botones
  function panel(opts) {
    const text = shareText(opts.report);
    const box = document.createElement('div');
    box.className = 'share-row';

    // El menú del celular puede llevar la foto: se descarga antes del clic, porque el navegador
    // exige que navigator.share se llame justo después del toque de la persona.
    let photoFile = null;
    if (opts.photoFile && navigator.canShare && navigator.canShare({ files: [opts.photoFile] })) {
      photoFile = opts.photoFile;  // foto que la persona acaba de elegir (formulario rápido)
    } else if (opts.photoUrl && navigator.canShare) {
      opts.photoUrl()
        .then((url) => fetch(url))
        .then((r) => (r.ok ? r.blob() : null))
        .then((blob) => {
          if (!blob) return;
          const file = new File([blob], 'mascota.jpg', { type: blob.type || 'image/jpeg' });
          if (navigator.canShare({ files: [file] })) photoFile = file;
        })
        .catch(() => { /* sin foto: se comparte solo el texto */ });
    }

    if (navigator.share) {
      box.append(button('share-native', 'Compartir', async () => {
        const data = { title: 'PetAlert IA', text };
        if (photoFile) data.files = [photoFile];
        try { await navigator.share(data); } catch (e) { /* la persona canceló */ }
      }));
    }
    box.append(
      button('share-whatsapp', 'WhatsApp', null, 'https://wa.me/?text=' + encodeURIComponent(text)),
      button('share-facebook', 'Facebook', null,
        'https://www.facebook.com/sharer/sharer.php?u=' + encodeURIComponent(window.location.origin + '/')),
      button('share-copy', 'Copiar texto', async (e) => {
        const btn = e.currentTarget;
        try {
          await navigator.clipboard.writeText(text);
          btn.textContent = '¡Copiado!';
          setTimeout(() => { btn.textContent = 'Copiar texto'; }, 2000);
          if (opts.onCopied) opts.onCopied();
        } catch (err) {
          window.prompt('Copia este texto:', text);
        }
      }));
    return box;
  }

  window.PetShare = { panel, shareText };
})();
