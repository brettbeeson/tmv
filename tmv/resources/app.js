"use strict";

let ws;
let rdws;
let lastImageUrl = "";

function tc(str) {
  if (str.length == 0) {
    return "";
  } else {
    var r = str.toLowerCase();
    return r[0].toUpperCase() + r.slice(1);
  }
}

/**
 * Set one radiobutton to active. Handle radiobuttons("checked"), Bootstrap buttons(parent.class="active").
 * @param {*} elements jQuery result with radiobutton - style element
 * @param {*} active_element_value Checked agains the "value" property of each elements
 */
function toggle_active(elements, active_element_value) {
  try {
    elements.each(function () {
      if (this.value == active_element_value) {
        this.checked = true;
        // radio
        this.classList.add("active");
        // bootstrap buttons
        this.parentNode.classList.add("active");
        // bootstrap buttons are sometimes controlled by their 'label' parent
      } else {
        this.checked = false;
        this.classList.remove("active");
        this.parentNode.classList.remove("active");
      }
    });
  } catch (exc) {
    console.log(exc);
  }
}

$(document).ready(function () {
  var editor = ace.edit("editor");
  editor.setTheme("ace/theme/xcode");
  editor.setFontSize(20);
  editor.session.setMode("ace/mode/toml");
  //toastr.options.preventDuplicates = true;
  toastr.options.positionClass = "toast-bottom-center";

  $("#services").on("click", function () {
    ws.emit("req-services-status");
  });
  $("#journal").on("click", function () {
    ws.emit("req-journal");
  });
  $("#files").on("click", function () {
    ws.emit("req-files");
  });
  $("#restart").on("click", function () {
    ws.emit("restart");
  });

  $("#camera-switch input").on("click", camera_switch);
  $("#upload-switch input").on("click", upload_switch);

  $("#save").on("click", function () {
    ws.emit("camera-config",editor.getValue());    
  });

  $("#cancel").on("click", function () {
    ws.emit("req-camera-config");
  });

  function camera_switch(e) {
    let position = e.target.value;
    ws.emit("switches", { camera: position });
  }

  function upload_switch(e) {
    let position = e.target.value;
    ws.emit("switches", { upload: position });
  }

  if ("WebSocket" in window) {
    connect();
  } else {
    alert("WebSockets are NOT supported by your browser!");
  }

  function connect() {
    if (ws) {
      if (ws.connected) {
        return;
      }
    }
    var loc = window.location;
    var new_uri;
    if (loc.protocol === "https:") {
      new_uri = "wss:";
    } else {
      new_uri = "ws:";
    }
    new_uri += "//" + loc.host;
    toastr.info("Connecting to " + new_uri);
    ws = io(new_uri);

    ws.on("connect", function () {
      ws.emit("req-camera-config");
      ws.emit("req-switches");
    });

    ws.on("camera-config", function (msg) {
        editor.setValue(msg.toml);
      
    });

    ws.on("switches", function (msg) {    
      // Unfocus current button as we are getting the real value from server
      let ae = document.activeElement;
      ae.blur();

      
        if ("camera" in msg) {
          toggle_active($("#camera-switch input"), tc(msg.camera));
        }
        if ("upload" in msg) {
          toggle_active($("#upload-switch input"), tc(msg.upload));
      
      }
    });

    ws.on("message", function (msg) {
      toastr.info(msg);
    });

    ws.on("warning", function (msg) {
      toastr.warning(msg);
    });

    ws.on("files", function (msg) {
      let logta = $("#log-textarea");
      logta.val(logta.val() + "FILES\n");

      for (let f in msg["files"]) {
        logta.val(logta.val() + msg["files"][f] + "\n");
      }
    });

    ws.on("services-status", function (msg) {
      let logta = $("#log-textarea");
      logta.val(logta.val() + "SERVICES\n");
      Object.keys(msg.services).forEach(function (key) {
        logta.val(logta.val() + key + " : " + msg.services[key] + "\n");
      });
      // autoscroll
      logta.scrollTop(logta[0].scrollHeight - logta.height());
    });

    ws.on("journal", function (msg) {
      let logta = $("#log-textarea");
      logta.val(logta.val() + "JOURNAL\n");
      if ("journal" in msg) {
        logta.val(logta.val() + msg["journal"]);
        // autoscroll
        logta.scrollTop(logta[0].scrollHeight - logta.height());
      }
    });

    ws.on("close", function () {
      toastr.warning("Closed connection");
    });

    ws.on("error", function () {
      toastr.error("Connection error");
      // interface blank out?
    });


  } /** end: on.connect */
  function statusCheck() {
    if (ws.connected) {
      $("#connection-status").html("Connected!")
      $("#connection-spinner").hide()
      //$("#connection-spinner").css({"visibility":"none"});
    } else {
      $("#connection-status").html("Connecting...")
      $("#connection-spinner").show()
      //$("#connection-spinner").css({"visibility":"visible"});
    }
    setTimeout(statusCheck, 1000);
  }
  setTimeout(statusCheck, 1000);
  
});
