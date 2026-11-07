// Loading state untuk form submissions & tombol aksi.
//
// Catatan: class "loading" sengaja TIDAK dipakai di sini karena di app.css
// class itu adalah spinner (elemen berputar). Memasangnya ke <form> atau
// <button> membuat teks/isi form ikut berputar. Di sini dipakai
// "is-submitting" yang hanya mengatur opacity & pointer-events.
document.addEventListener("DOMContentLoaded", function () {
  // Form loading state
  document.querySelectorAll("form").forEach(function (form) {
    form.addEventListener("submit", function () {
      if (form.classList.contains("is-submitting")) {
        return;
      }
      form.classList.add("is-submitting");

      var submitBtn = form.querySelector('button[type="submit"]');
      if (submitBtn) {
        submitBtn.classList.add("is-submitting");
        submitBtn.disabled = true;
        submitBtn.setAttribute("aria-busy", "true");
      }
    });
  });

  // Button loading state untuk delete/action buttons
  document.querySelectorAll("[data-loading-action]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      if (!this.classList.contains("is-submitting")) {
        this.classList.add("is-submitting");
        this.disabled = true;
        this.setAttribute("aria-busy", "true");
      }
    });
  });

  // Jangan biarkan state tombol tertinggal saat halaman dipulihkan dari
  // bfcache (tombol tetap disabled padahal halaman sudah kembali).
  window.addEventListener("pageshow", function () {
    document.querySelectorAll(".is-submitting").forEach(function (el) {
      el.classList.remove("is-submitting");
      if (el.tagName === "BUTTON") {
        el.disabled = false;
      }
      el.removeAttribute("aria-busy");
    });
  });
});
