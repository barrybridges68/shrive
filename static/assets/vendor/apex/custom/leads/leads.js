var options = {
  series: [
    {
      name: "",
      data: [200, 330, 548, 740, 880],
    },
  ],
  chart: {
    type: "bar",
    height: 240,
    toolbar: {
      show: false,
    },
  },
  dataLabels: {
    enabled: false,
  },
  plotOptions: {
    bar: {
      borderRadius: 0,
      horizontal: true,
      distributed: true,
      barHeight: "80%",
      isFunnel: true,
    },
  },
  colors: [
    "#338dd7", "#3a97e0", "#42a1e9", "#4aabf2", "#52b5fb"
  ],
  dataLabels: {
    enabled: true,
    formatter: function (val, opt) {
      return opt.w.globals.labels[opt.dataPointIndex];
    },
    dropShadow: {
      enabled: true,
    },
  },
  xaxis: {
    categories: [
      "New",
      "Contacted",
      "Qualified",
      "Proposal Sent",
      "Closed Won/Lost",
    ],
  },
  legend: {
    show: false,
  },
};

var chart = new ApexCharts(document.querySelector("#leads"), options);
chart.render();