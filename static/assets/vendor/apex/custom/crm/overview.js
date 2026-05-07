var options = {
  series: [75],
  chart: {
    height: 270,
    type: "radialBar",
    offsetY: -10,
  },
  plotOptions: {
    radialBar: {
      startAngle: -135,
      endAngle: 135,
      track: {
        background: '#516c83',
        strokeWidth: '100%',
        opacity: 0.5,
      },
      dataLabels: {
        name: {
          fontSize: "16px",
          color: undefined,
          offsetY: 0,
        },
        value: {
          offsetY: 20,
          fontSize: "21px",
          color: undefined,
          formatter: function (val) {
            return val + "%";
          },
        },
      },
    },
  },
  colors: ['#338dd7', '#4aa3e5', '#61b9f2', '#78ceff', '#8fe2ff', '#a6f8ff'],
  stroke: {
    dashArray: 4,
  },
  labels: ["Overview"],
};

var chart = new ApexCharts(document.querySelector("#productOverview"), options);
chart.render();