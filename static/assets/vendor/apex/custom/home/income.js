var options = {
  chart: {
    height: 307,
    type: "bar",
    toolbar: {
      show: false,
    },
  },
  dataLabels: {
    enabled: false,
  },
  stroke: {
    show: true,
    width: 3,
    colors: ['transparent']
  },
  plotOptions: {
    bar: {
      columnWidth: "25%",
      borderRadius: 6,
    },
  },
  series: [
    {
      name: "Income",
      data: [10, 20, 30, 40, 50, 60, 70],
    },
    {
      name: "Expenses",
      data: [15, 25, 35, 45, 55, 65, 75],
    },
  ],
  grid: {
    borderColor: "#3f4c5c",
    xaxis: {
      lines: {
        show: true,
      },
    },
    yaxis: {
      lines: {
        show: false,
      },
    },
    padding: {
      top: 0,
      right: 0,
      bottom: 10,
      left: 0,
    },
  },
  xaxis: {
    categories: [
      "Mon",
      "Tue",
      "Wed",
      "Thu",
      "Fri",
      "Sat",
      "Sun",
    ],
  },
  yaxis: {
    labels: {
      show: false,
    },
  },
  colors: ["#5fb1f4", "#a186e4"],
  markers: {
    size: 0,
    opacity: 0.3,
    colors: ["#5fb1f4", "#a186e4"],
    strokeColor: "#ffffff",
    strokeWidth: 2,
    hover: {
      size: 7,
    },
  },
  tooltip: {
    y: {
      formatter: function (val) {
        return '$' + val + '' + 'k';
      },
    },
    theme: 'dark',
  },
};

var chart = new ApexCharts(document.querySelector("#income"), options);

chart.render();
