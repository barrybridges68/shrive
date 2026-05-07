document.addEventListener('DOMContentLoaded', function () {
  // Basic Editor
  var basicEditor = new Quill('#basic-quill-editor', {
    modules: {
      toolbar: [
        ['bold', 'italic'],
        ['link', 'blockquote'],
        [{ list: 'ordered' }, { list: 'bullet' }]
      ]
    },
    theme: 'snow'
  });

  // Snow Theme
  var snowEditor = new Quill('#snow-editor', {
    modules: {
      toolbar: [
        [{ 'header': [1, 2, 3, 4, 5, 6, false] }],
        ['bold', 'italic', 'underline', 'strike'],
        [{ 'color': [] }, { 'background': [] }],
        [{ 'align': [] }],
        ['link', 'image', 'video'],
        ['clean']
      ]
    },
    theme: 'snow'
  });

  // Bubble Theme
  var bubbleEditor = new Quill('#bubble-editor', {
    modules: {
      toolbar: [
        ['bold', 'italic'],
        ['link'],
        [{ 'header': 1 }, { 'header': 2 }],
        [{ 'list': 'ordered' }, { 'list': 'bullet' }]
      ]
    },
    theme: 'bubble'
  });

  // Full Featured Editor
  var fullEditor = new Quill('#full-editor', {
    modules: {
      toolbar: [
        [{ 'header': [1, 2, 3, 4, 5, 6, false] }],
        ['bold', 'italic', 'underline', 'strike'],
        [{ 'font': [] }],
        [{ 'size': ['small', false, 'large', 'huge'] }],
        [{ 'color': [] }, { 'background': [] }],
        [{ 'align': [] }],
        ['blockquote', 'code-block'],
        [{ 'list': 'ordered' }, { 'list': 'bullet' }],
        [{ 'script': 'sub' }, { 'script': 'super' }],
        [{ 'indent': '-1' }, { 'indent': '+1' }],
        ['link', 'image', 'video'],
        ['clean']
      ]
    },
    theme: 'snow'
  });
});