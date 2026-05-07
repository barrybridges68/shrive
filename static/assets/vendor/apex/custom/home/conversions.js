var options = {
  chart: {
    width: 300,
    type: "pie",
  },
  labels: ["Google", "Twitter", "Instagram", "Google", "Youtube"],
  series: [20, 34, 56, 25, 53],
  legend: {
    position: "bottom",
  },
  dataLabels: {
    enabled: false,
  },
  stroke: {
    width: 0,
  },
  colors: ["#e962a8", "#a271d7", "#628bf0", "#50c356", "#f9c851"],
};
var chart = new ApexCharts(document.querySelector("#conversions"), options);
chart.render();