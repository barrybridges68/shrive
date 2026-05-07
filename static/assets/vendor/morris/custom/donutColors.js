// Morris Donut
Morris.Donut({
  element: "donutColors",
  data: [
    { value: 30, label: "foo" },
    { value: 15, label: "bar" },
    { value: 10, label: "baz" },
    { value: 5, label: "A really really long label" },
  ],
  backgroundColor: "#bccee2",
  labelColor: "#bccee2",
  colors: ["#e962a8", "#a271d7", "#628bf0", "#50c356", "#f9c851"],
  resize: true,
  hideHover: "auto",
  gridLineColor: "#3f4c5c",
  formatter: function (x) {
    return x + "%";
  },
});
