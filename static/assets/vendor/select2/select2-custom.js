$(document).ready(function () {
  // Basic searchable select
  $('.select2').select2({
    width: '100%',
    placeholder: 'Select an option'
  });

  // Multi-select
  $('.select2-multi').select2({
    width: '100%',
    placeholder: 'Select options'
  });

  // Tags
  $('.select2-tags').select2({
    width: '100%',
    tags: true,
    tokenSeparators: [',', ' '],
    placeholder: 'Select or add tags'
  });

  // Icon select
  $('.select2-icons').select2({
    width: '100%',
    templateSelection: formatIconSelection,
    templateResult: formatIconOption,
    escapeMarkup: function (m) { return m; }
  });

  // Selection limit
  $('.select2-limit').select2({
    width: '100%',
    maximumSelectionLength: 3,
    placeholder: 'Select up to 3 months'
  });

  // Format icon options
  function formatIconOption(option) {
    if (!option.id) { return option.text; }
    return '<i class="' + $(option.element).data('icon') + ' me-2"></i>' + option.text;
  }

  // Format selected icon option
  function formatIconSelection(option) {
    if (!option.id) { return option.text; }
    return '<i class="' + $(option.element).data('icon') + ' me-2"></i>' + option.text;
  }
});
