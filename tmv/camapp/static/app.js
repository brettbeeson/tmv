"use strict";

let ws;
const TMV_SERVER = "http://home.brettbeeson.com.au/"

function camera_switch(e) {
  let position = e.target.value;
  ws.emit("switches", { camera: position });
  ws.emit("req_switches");
}

function upload_switch(e) {
  let position = e.target.value;
  ws.emit("switches", { upload: position });
  ws.emit("req_switches");
}

$(document).ready(function () {
  var editor = ace.edit("editor");
  editor.setTheme("ace/theme/xcode");
  editor.setFontSize(20);
  editor.session.setMode("ace/mode/toml");
  //toastr.options.preventDuplicates = true;
  toastr.options.positionClass = "toast-bottom-center";

  if ("WebSocket" in window) {
    connect();
  } else {
    alert("WebSockets are NOT supported by your browser!");
  }

  // Redirect to http://localhost:80/index.php to pickup lighttpd server with raspap
  $("#wifi").on("click", function() {
    let raspap = $("#wifi").attr("href");
      window.open(raspap,"_blank");
      // window.open(raspap,"_self"); same window
  });
  $("#wifi").attr("href",location.protocol + "//" + location.hostname+ ":80/index.php")
  
  $("#server").on("click", function() {
    // force open in new tab
    // set via camera_name
    let server = $("#server").attr("href");    
      window.open(server,"_blank");
  });
  
  

  
  $("#services").on("click", function () {
    ws.emit("req_services_status");
  });
  $("#journal").on("click", function () {
    ws.emit("req_journal");
  });
  $("#files").on("click", function () {
    ws.emit("req_files");
  });
  $("#error").on("click", () => ws.emit("raise_error"));
  
  $("#restart").on("click", function () {
    ws.emit("restart_service");
  });
  $("#saveandrestart").on("click", function () {
    ws.emit("camera_config", editor.getValue());
    ws.emit("restart_service");
  });

  $("#camera-switch input").on("click", camera_switch);
  $("#upload-switch input").on("click", upload_switch);

  $("#save").on("click", function () {
    ws.emit("camera_config", editor.getValue());
  });

  $("#cancel").on("click", function () {
    ws.emit("req_camera_config");
  });


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
      ws.emit("req_camera_config");
      ws.emit("req_switches");
      ws.emit("req_camera_name");
    });

    ws.on("camera_config", msg =>editor.setValue(msg.toml));
    
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

    ws.on("message", msg =>  toastr.info(msg));
  
    ws.on("warning", msg => toastr.warning(msg));

    ws.on("camera_name", msg => {
      $('#camera-name').text(msg);
      document.title = "TMV - " + msg
      $('#server').attr('href',TMV_SERVER + msg)
      
    });
    
    ws.on("files", function (msg) {
      let logta = $("#log-textarea");
      logta.val(logta.val() + "FILES\n");

      for (let f in msg["files"]) {
        logta.val(logta.val() + msg["files"][f] + "\n");
      }
       // autoscroll
       logta.scrollTop(logta[0].scrollHeight - logta.height());
    });

    ws.on("services_status", function (msg) {
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
  
    ws.on("image", function (msg) {
      let imgtag = $("#image");
      let src
      if ("src-bin" in msg) {
        // To fix
        src = "data:image/jpeg;base64," + _arrayBufferToBase64(msg["src-bin"]);
      } else if ("src-b64" in msg) {
        src = msg["src-b64"];
        src = "data:image/jpeg;base64," + msg["src-b64"];
      } else {
        console.log("Error: Bad Image: " + msg);
      }
      imgtag.attr("src", src);
      toastr.info("Updated image")
    });

    ws.on("close", () => toastr.warning("Closed connection"));
    
    ws.on("error",()  => toastr.error("Connection error"));
    
  } /** end: on.connect */
  setTimeout(statusCheck, 1000);
});

function statusCheck() {
  if (ws.connected) {
    $("#connection-status").html("Connected");
    $("#connection-spinner").hide();
  } else {
    $("#connection-status").html("Connecting");
    $("#connection-spinner").show();
  }
  setTimeout(statusCheck, 1000);
}


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
function _arrayBufferToBase64( buffer ) {
  var binary = '';
  var bytes = new Uint8Array( buffer );
  var len = bytes.byteLength;
  for (var i = 0; i < len; i++) {
      binary += String.fromCharCode( bytes[ i ] );
  }
  return window.btoa( binary );
}