/* Interaksi kecil: buka dialog transaksi dan isi formnya. */

(function () {
  "use strict";

  var dialog = document.getElementById("tx-dialog");
  if (!dialog) {
    return;
  }

  var pickerDialog = document.getElementById("picker-dialog");

  window.openPicker = function () {
    if (pickerDialog) {
      pickerDialog.showModal();
    }
  };

  window.closePicker = function () {
    if (pickerDialog) {
      pickerDialog.close();
    }
  };

  var form = document.getElementById("tx-form");
  var title = document.getElementById("tx-dialog-title");
  var transferGroup = document.getElementById("transfer-group");

  function applyKind(kind) {
    transferGroup.hidden = kind !== "transfer";
  }

  window.openTxCreate = function () {
    form.reset();
    form.action = "/transactions/create";
    title.textContent = "Transaksi baru";
    form.elements["occurred_at"].value = form.dataset.defaultOccurred;
    form.elements["kind"].value = "expense";
    applyKind("expense");
    dialog.showModal();
    form.elements["amount"].focus();
  };

  window.openTxEdit = function (button) {
    var data = JSON.parse(button.dataset.tx);

    form.action = "/transactions/" + data.id + "/update";
    title.textContent = "Ubah transaksi";
    form.elements["kind"].value = data.kind;
    form.elements["amount"].value = data.amount;
    form.elements["account_id"].value = String(data.account_id);
    if (data.kind === "transfer" && data.to_account_id) {
      form.elements["to_account_id"].value = String(data.to_account_id);
    }
    form.elements["category_id"].value = String(data.category_id);
    form.elements["merchant"].value = data.merchant;
    form.elements["note"].value = data.note;
    form.elements["occurred_at"].value = data.occurred_at;

    applyKind(data.kind);
    dialog.showModal();
  };

  window.closeTxDialog = function () {
    dialog.close();
  };

  // OCR upload preview modal
  var uploadPreviewDialog = document.getElementById("upload-preview-dialog");
  var saveUploadBtn = document.getElementById("save-upload-btn");

  window.openUpload = function () {
    if (!uploadPreviewDialog) {
      return;
    }
    getFileInput().click();
  };

  window.closeUploadPreview = function () {
    if (uploadPreviewDialog) {
      uploadPreviewDialog.close();
    }
  };

  // Hidden file input for OCR (created on first click to ensure DOM ready)
  var fileInput = null;

  function getFileInput() {
    if (!fileInput) {
      fileInput = document.createElement("input");
      fileInput.type = "file";
      fileInput.id = "file-input";
      fileInput.accept = "image/*";
      fileInput.style.display = "none";
      fileInput.addEventListener("change", handleFileSelect);
      document.body.appendChild(fileInput);
    }
    return fileInput;
  }

  function handleFileSelect(event) {
    var file = event.target.files[0];
    if (!file) {
      return;
    }

    var reader = new FileReader();
    reader.onload = function (e) {
      document.getElementById("preview-image").src = e.target.result;
      document.getElementById("preview-text").textContent = "Membaca struk...";
      document.getElementById("preview-amount").value = "";
      document.getElementById("preview-merchant").value = "";
      document.getElementById("preview-date").value = "";
      document.getElementById("preview-category").selectedIndex = 0;
      document.getElementById("preview-account").selectedIndex = 0;

      var formData = new FormData();
      formData.append("file", file);

      fetch("/ocr", {
        method: "POST",
        body: formData,
      })
        .then(function (res) {
          if (!res.ok) {
            throw new Error("OCR failed");
          }
          return res.json();
        })
        .then(function (data) {
          document.getElementById("preview-amount").value = data.amount || "";
          document.getElementById("preview-merchant").value = data.merchant || "";
          document.getElementById("preview-date").value = data.occurred_at || "";
          document.getElementById("preview-text").textContent = data.text || "";
          if (data.category_id) {
            document.getElementById("preview-category").value = data.category_id;
          }
          if (data.account_id) {
            document.getElementById("preview-account").value = data.account_id;
          }
          uploadPreviewDialog.showModal();
        })
        .catch(function (err) {
          document.getElementById("preview-text").textContent = "OCR gagal: " + err.message;
        });
    };
    reader.readAsDataURL(file);
  }

  // Save OCR preview to transaction
  var saveUploadBtn = document.getElementById("save-upload-btn");
  if (saveUploadBtn) {
    saveUploadBtn.addEventListener("click", function () {
      var amount = document.getElementById("preview-amount").value;
      var merchant = document.getElementById("preview-merchant").value;
      var occurred_at = document.getElementById("preview-date").value;
      var category_id = document.getElementById("preview-category").value;
      var account_id = document.getElementById("preview-account").value;

      // Validate required fields
      if (!amount || isNaN(amount) || parseFloat(amount) <= 0) {
        alert("Nominal wajib diisi dan harus > 0");
        return;
      }
      if (!merchant || merchant.trim().length === 0) {
        alert("Nama merchant/warung wajib diisi");
        return;
      }
      if (!occurred_at) {
        alert("Tanggal transaksi wajib diisi");
        return;
      }
      if (!category_id || category_id === "0") {
        alert("Kategori wajib dipilih");
        return;
      }
      if (!account_id || account_id === "0") {
        alert("Dompet sumber wajib dipilih");
        return;
      }

      // Create transaction via form submission
      var form = document.getElementById("tx-form");
      if (!form) {
        alert("Form transaksi tidak ditemukan");
        return;
      }

      form.reset();
      form.action = "/transactions/create";
      form.elements["amount"].value = amount;
      form.elements["merchant"].value = merchant;
      form.elements["occurred_at"].value = occurred_at;
      form.elements["category_id"].value = category_id;
      form.elements["account_id"].value = account_id;
      form.elements["kind"].value = "expense";

      closeUploadPreview();
      dialog.showModal();
      form.elements["note"].focus();
    });
  }
})();
