(function ($) {
  $.sidebarMenu = function (menu) {
    const animationSpeed = 300;

    $(menu).on("click", "li a", function (e) {
      const $this = $(this);
      const checkElement = $this.next();

      if (checkElement.is(".treeview-menu")) {
        e.preventDefault();

        if (checkElement.is(":visible")) {
          checkElement.slideUp(animationSpeed, () => {
            checkElement.removeClass("menu-open");
          });
          checkElement.parent("li").removeClass("active");
        } else {
          const parent = $this.parents("ul").first();
          const visibleMenus = parent.find("ul:visible").slideUp(animationSpeed);
          visibleMenus.removeClass("menu-open");

          const parentLi = $this.parent("li");
          checkElement.slideDown(animationSpeed, () => {
            checkElement.addClass("menu-open");
            parent.find("li.active").removeClass("active");
            parentLi.addClass("active");
          });
        }
      }
    });
  };

  // Initialize sidebar menu
  $.sidebarMenu($(".sidebar-menu"));

  $(function () {
    // Toggle sidebar
    $(".toggle-sidebar").on("click", function () {
      $(".page-wrapper").toggleClass("toggled");
    });

    // Pin sidebar
    $(".pin-sidebar").on("click", function () {
      const pageWrapper = $(".page-wrapper");
      const sidebar = $("#sidebar");

      if (pageWrapper.hasClass("pinned")) {
        pageWrapper.removeClass("pinned");
        sidebar.off("hover");
      } else {
        pageWrapper.addClass("pinned");
        sidebar.hover(
          () => pageWrapper.addClass("sidebar-hovered"),
          () => pageWrapper.removeClass("sidebar-hovered")
        );
      }
    });

    // Toggle overlay
    $("#overlay").on("click", function () {
      $(".page-wrapper").toggleClass("toggled");
    });

    // Window resize handlers
    $(window).on("resize", function () {
      const pageWrapper = $(".page-wrapper");
      if ($(window).width() <= 768) {
        pageWrapper.removeClass("pinned");
      } else if ($(window).width() > 768) {
        pageWrapper.removeClass("toggled");
      }
    });

    // Card loader
    $(".card-loader").fadeOut(2000);

    // Display current month
    const monthNames = [
      "January", "February", "March", "April",
      "May", "June", "July", "August",
      "September", "October", "November", "December"
    ];
    $(".monthDisplay").text(`In ${monthNames[new Date().getMonth()]}`);

    // Toggle buttons
    $(".toggle-btns .btn, .toggle-btn-group .btn").on("click", function () {
      const group = $(this).closest(".toggle-btns, .toggle-btn-group");
      group.find(".btn").removeClass("btn-primary").addClass("btn-outline-primary");
      $(this).addClass("btn-primary").removeClass("btn-outline-primary");
    });

    // Fullscreen card toggle
    const toggleCardFullscreen = (cardId, toggleButtonId, fullscreenClass) => {
      const toggleButton = document.getElementById(toggleButtonId);
      const card = document.getElementById(cardId);

      if (toggleButton && card) {
        toggleButton.addEventListener("click", () => {
          card.classList.toggle(fullscreenClass);
        });
      }
    };

    toggleCardFullscreen("cardFullscreen", "toggleCardFullscreen", "card-fullscreen");

    // Bootstrap tooltips and popovers
    document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => new bootstrap.Tooltip(el));
    document.querySelectorAll('[data-bs-toggle="popover"]').forEach(el => new bootstrap.Popover(el));

    // Toast example
    const toastTrigger = document.getElementById("downloadDataToast");
    const toastLiveExample = document.getElementById("downloadData");

    if (toastTrigger) {
      const toastBootstrap = bootstrap.Toast.getOrCreateInstance(toastLiveExample);
      toastTrigger.addEventListener("click", () => toastBootstrap.show());
    }
  });
})(jQuery);