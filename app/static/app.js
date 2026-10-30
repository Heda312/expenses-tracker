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
  var kindSelect = document.getElementById("tx-kind");
  var transferGroup = document.getElementById("transfer-group");

  function applyKind(kind) {
    transferGroup.hidden = kind !== "transfer";
  }

  // Toggle "Ke dompet" field when kind changes
  if (kindSelect) {
    kindSelect.addEventListener("change", function () {
      applyKind(this.value);
    });
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
    // Hide loading overlay
    var loading = document.getElementById("upload-loading");
    if (loading) {
      loading.style.display = "none";
    }
  };

  // Custom alert modal
  var alertDialog = document.getElementById("alert-dialog");
  var alertContent = document.getElementById("alert-content");

  window.showAlert = function (message) {
    if (!alertDialog || !alertContent) {
      alert(message);
      return;
    }
    alertContent.textContent = message;
    alertDialog.showModal();
  };

  window.closeAlertDialog = function () {
    if (alertDialog) {
      alertDialog.close();
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
      document.getElementById("preview-text").textContent = "";
      document.getElementById("preview-amount").value = "";
      document.getElementById("preview-merchant").value = "";
      document.getElementById("preview-date").value = "";
      document.getElementById("preview-category").selectedIndex = 0;
      document.getElementById("preview-account").selectedIndex = 0;

      // Show loading overlay
      var loading = document.getElementById("upload-loading");
      if (loading) {
        loading.style.display = "flex";
      }

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
          // Hide loading before showing modal
          if (loading) {
            loading.style.display = "none";
          }
          uploadPreviewDialog.showModal();
        })
        .catch(function (err) {
          if (loading) {
            loading.style.display = "none";
          }
          document.getElementById("preview-text").textContent = "OCR gagal: " + err.message;
        });
    };
    reader.readAsDataURL(file);
  }

  // Save OCR preview to transaction
  var saveUploadBtn = document.getElementById("save-upload-btn");
  if (saveUploadBtn) {
    saveUploadBtn.addEventListener("click", function () {
      var validated = validatePreviewForm();
      if (!validated) {
        return;
      }

      // Create transaction via form submission
      var form = document.getElementById("tx-form");
      if (!form) {
        showAlert("Form transaksi tidak ditemukan");
        return;
      }

      form.reset();
      form.action = "/transactions/create";
      form.elements["amount"].value = validated.amount;
      form.elements["merchant"].value = validated.merchant;
      form.elements["occurred_at"].value = validated.occurred_at;
      form.elements["category_id"].value = validated.category_id;
      form.elements["account_id"].value = validated.account_id;
      form.elements["kind"].value = "expense";

      closeUploadPreview();
      dialog.showModal();
      form.elements["note"].focus();
    });
  }

  // Validation for OCR preview — show popup alert
  function validatePreviewForm() {
    var errors = [];
    var amount = document.getElementById("preview-amount").value;
    var merchant = document.getElementById("preview-merchant").value;
    var occurred_at = document.getElementById("preview-date").value;
    var category_id = document.getElementById("preview-category").value;
    var account_id = document.getElementById("preview-account").value;

    if (!amount || isNaN(amount) || parseFloat(amount) <= 0) {
      errors.push("Nominal harus > 0");
    }
    if (!merchant || merchant.trim().length === 0) {
      errors.push("Nama merchant/warung wajib diisi");
    }
    if (!occurred_at) {
      errors.push("Tanggal transaksi wajib diisi");
    }
    if (!category_id || category_id === "0") {
      errors.push("Kategori wajib dipilih");
    }
    if (!account_id || account_id === "0") {
      errors.push("Dompet sumber wajib dipilih");
    }

    if (errors.length > 0) {
      showAlert(errors.join("\n"));
      return null;
    }
    return {
      amount: parseFloat(amount),
      merchant: merchant.trim(),
      occurred_at: occurred_at,
      category_id: parseInt(category_id, 10),
      account_id: parseInt(account_id, 10),
    };
  }
})();
