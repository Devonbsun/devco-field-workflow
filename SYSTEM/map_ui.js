/* Pin actions always carry the job and JU visible when the map was opened. */
function attachJuPin(marker, point, job, stop) {
  const params = new URLSearchParams({job, ju: point.ju}).toString();
  const recordUrl = '/record?' + params;
  let lastClick = null, opening = false, refresh = 0;
  function openRecord(event) {
    if (event && event.originalEvent) L.DomEvent.stop(event.originalEvent);
    if (opening) return;
    opening = true;
    window.location.assign(recordUrl);
  }
  function popup(data) {
    const root = document.createElement('div');
    root.className = 'ju-popup';
    const add = (tag, text, parent = root) => {
      const node = document.createElement(tag);
      node.textContent = text;
      parent.append(node);
      return node;
    };
    add('strong', 'JU ' + point.ju);
    if (stop) add('div', 'Route stop ' + stop);
    add('div', point.address || 'No address recorded');
    add('b', data.done ? 'COMPLETED' : 'NOT COMPLETE');
    const field = (label, value) => {
      const section = add('div', '');
      section.className = 'ju-popup-field';
      add('b', label, section);
      add('div', value, section);
    };
    if (point.condition_code || point.condition_desc) {
      field('Work order', [point.condition_code, point.condition_desc].filter(Boolean).join(' · '));
    }
    field('Billing codes', (data.billing || []).map(([code, qty]) => code + ' ×' + qty).join('\n') || 'No billing codes recorded');
    field('Notes', data.note || 'No notes recorded');
    field('Close code', data.status || 'Not closed');
    field('Pole coordinates', point.lat + ', ' + point.lon);
    const actions = add('div', '');
    actions.className = 'ju-popup-actions';
    for (const [label, path] of [['Open JU', '/record'], ['Navigate', '/navigate'], ['Find pole', '/hone']]) {
      const link = add('a', label, actions);
      link.href = path + '?' + params;
      link.className = path === '/navigate' ? 'nav' : 'activate';
    }
    const form = add('form', '');
    form.method = 'post'; form.action = '/activate';
    for (const [name, value] of [['job', job], ['ju', point.ju]]) {
      const input = document.createElement('input');
      input.type = 'hidden'; input.name = name; input.value = value; form.append(input);
    }
    add('button', 'Make Active JU', form).className = 'activate';
    add('small', 'Double-tap the pin to open this JU.');
    return root;
  }
  marker.bindPopup(popup(point), {
    // Keep the pin under the finger between taps; a popup must not pan it away.
    autoPan: false, offset: L.point(0, -18), maxWidth: 320,
    maxHeight: Math.max(180, Math.min(420, window.innerHeight - 220)),
  });
  // Android may suppress the second synthetic click during a double-tap.
  // Count actual short touch releases too, without treating a drag as a tap.
  const element = marker.getElement();
  if (element && window.PointerEvent) {
    let start = null, lastTouch = null;
    element.style.touchAction = 'manipulation';
    element.addEventListener('pointerdown', event => {
      if (event.pointerType !== 'mouse' && event.isPrimary)
        start = {x: event.clientX, y: event.clientY, time: Date.now()};
    });
    element.addEventListener('pointercancel', () => { start = null; lastTouch = null; });
    element.addEventListener('pointerup', event => {
      if (!start || event.pointerType === 'mouse' || !event.isPrimary) return;
      const now = Date.now();
      const tapped = now - start.time < 350 && Math.hypot(event.clientX - start.x, event.clientY - start.y) < 12;
      start = null;
      if (!tapped) { lastTouch = null; return; }
      if (lastTouch !== null && now - lastTouch < 450) openRecord({originalEvent: event});
      lastTouch = now;
    });
  }
  marker.on('click', event => {
    const now = Date.now();
    if (lastClick !== null && now - lastClick < 450) openRecord(event);
    lastClick = now;
  });
  marker.on('dblclick', openRecord);
  marker.on('popupopen', async () => {
    const request = ++refresh;
    // Once the double-tap window passes, bring the whole popup into view.
    setTimeout(() => {
      if (opening || !marker.isPopupOpen() || request !== refresh) return;
      const panel = marker.getPopup();
      panel.options.autoPanPaddingTopLeft = L.point(10, document.getElementById('bar').offsetHeight + 25);
      panel.options.autoPan = true;
      panel.update();
      panel.options.autoPan = false;
    }, 480);
    try {
      const response = await fetch('/map-record?' + params, {cache: 'no-store'});
      if (!response.ok) throw Error('Record unavailable');
      const current = await response.json();
      if (request === refresh && marker.isPopupOpen()) marker.setPopupContent(popup(current));
    } catch (_) {
      if (marker.isPopupOpen()) {
        const notice = document.createElement('p');
        notice.textContent = 'Could not refresh. Showing the record loaded with this map.';
        marker.getPopup().getContent().append(notice);
      }
    }
  });
  marker.on('popupclose', () => { refresh++; });
}
