/* Shared local-file input for image search. No URL fetching or network requests. */
(function (root) {
  'use strict';
  var MAX_BYTES = 20 * 1024 * 1024;
  function hasFiles(dt) {
    return !!dt && (Array.prototype.indexOf.call(dt.types || [], 'Files') !== -1 || (dt.files && dt.files.length > 0));
  }
  function validate(files) {
    if (!files || !files.length) return 'img_file_empty';
    if (files.length !== 1) return 'img_file_one';
    var file = files[0];
    if (!/^image\//i.test(file.type || '')) return 'img_file_type';
    if (!file.size || file.size > MAX_BYTES) return 'img_file_size';
    return null;
  }
  function bind(options) {
    var doc = options.document || document;
    var zone = options.zone;
    var input = options.input;
    var depth = 0;
    function reset() { depth = 0; zone.classList.remove('is-dragging'); }
    function accept(files) {
      var error = validate(files);
      if (error) { options.onError(error); return false; }
      options.onError('');
      options.onFile(files[0]);
      return true;
    }
    zone.addEventListener('dragenter', function (e) {
      if (!hasFiles(e.dataTransfer)) return;
      e.preventDefault(); depth++; zone.classList.add('is-dragging');
    });
    zone.addEventListener('dragover', function (e) {
      if (!hasFiles(e.dataTransfer)) return;
      e.preventDefault(); e.dataTransfer.dropEffect = 'copy';
    });
    zone.addEventListener('dragleave', function (e) {
      if (!depth) return;
      e.preventDefault(); depth = Math.max(0, depth - 1);
      if (!depth) reset();
    });
    zone.addEventListener('drop', function (e) {
      if (!hasFiles(e.dataTransfer)) return;
      e.preventDefault(); e.stopPropagation(); reset(); accept(e.dataTransfer.files);
    });
    input.addEventListener('change', function () {
      var files = Array.prototype.slice.call(input.files || []);
      input.value = '';
      if (files.length) accept(files); // Cancelling the picker is not an error.
    });
    // Prevent a missed file drop from navigating away from the site. Text/links retain their normal behavior.
    doc.addEventListener('dragover', function (e) { if (hasFiles(e.dataTransfer)) e.preventDefault(); });
    doc.addEventListener('drop', function (e) { if (hasFiles(e.dataTransfer)) e.preventDefault(); reset(); });
    doc.addEventListener('dragend', reset);
    if (doc.defaultView) doc.defaultView.addEventListener('blur', reset);
    return { accept: accept, reset: reset };
  }
  root.BoopaImageDrop = { bind: bind, validate: validate, maxBytes: MAX_BYTES };
  if (typeof module === 'object' && module.exports) module.exports = root.BoopaImageDrop;
})(typeof window !== 'undefined' ? window : globalThis);
