$(".stop-continue-example").webTicker({
  height: 'auto',
  duplicate: true,
  rssfrequency: 0,
  startEmpty: false,
  hoverpause: false,
  transition: "ease"
});


$(function () {

  'use strict';
  //ticker
  if ($('.webticker-default').length) {
    $(".webticker-default").webTicker({
      height: 'auto',
      duplicate: true,
      startEmpty: false,
      rssfrequency: 5,
      direction: 'left'
    });
  }


}); // End of use strict