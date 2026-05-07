var options = {
  chart: {
    width: 300,
    type: "donut",
  },
  labels: ["Team A", "Team B", "Team C", "Team D", "Team E"],
  series: [20, 20, 20, 20, 20],
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
var chart = new ApexCharts(document.querySelector("#donut"), options);
chart.render();
