"use strict";

let ws;
const TMV_SERVER = "http://home.brettbeeson.com.au/"

function mode(e) {
  let position = e.target.value;
  ws.emit("mode",  position );
  ws.emit("req-mode");
}

function speed(e) {
  let position = e.target.value;
  ws.emit("speed", position );
  ws.emit("req-speed");
}

$(document).ready(function () {
  var editor = ace.edit("editor");
  editor.setTheme("ace/theme/xcode");
  editor.setFontSize(20);
  editor.session.setMode("ace/mode/toml");

  var wifieditor = ace.edit("wifieditor");
  wifieditor.setTheme("ace/theme/xcode");
  wifieditor.setFontSize(20);
  //wifieditor.session.setMode("ace/mode/wpa?");
  


  //toastr.options.preventDuplicates = true;
  toastr.options.positionClass = "toast-bottom-center";

  if ("WebSocket" in window) {
    //connect("ws://localhost:5000");
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
    ws.emit("req-services-status");
  });
  $("#journal").on("click", function () {
    ws.emit("req-journal");
  });
  $("#files").on("click", function () {
    ws.emit("req-files");
  });
  $("#error").on("click", () => ws.emit("raise-error"));
  $("#latest-image-time").on("click", () => ws.emit("req-latest-image-time"));
  
  $("#restart").on("click", function () {
    ws.emit("restart-camera");
  });
  $("#saveandrestart").on("click", function () {
    ws.emit("camera-config", editor.getValue());
    ws.emit("restart-camera");
  });

  $("#wifi-save").on("click", function () {
    ws.emit("wpa-supplicant", wifieditor.getValue());
  });

  $("#wifi-scan").on("click", function () {
    ws.emit("req-wpa-scan");
  });

  $("#wifi-cancel").on("click", function () {
    ws.emit("req-wpa-supplicant");
  });

  $("#wifi-reconfigure").on("click", function () {
    ws.emit("wpa-reconfigure");
  });

  $("#camera-mode input").on("click", mode);

  $("#camera-speed  input").on("click", speed);

  $("#save").on("click", function () {
    ws.emit("camera-config", editor.getValue());
  });

  $("#cancel").on("click", function () {
    ws.emit("req-camera-config");
  });

  
  
  let cropper
  let zoom
  let cropbox
  
  $("#zoom").on("click",() => {  
    $('#zoom-image').remove()
    $('#zoom-image-div').empty()
    $('#zoom-image-div').append("<img id='zoom-image'/>")
    let current_image_src = $('#image').attr("src")
    $('#zoom-image').attr("src", current_image_src);
   });
  $("#modal-zoom").on("shown.bs.modal", function() {
    // Only get the Cropper.js instance after initialized
    var $image = $('#zoom-image');
    
    $image.cropper({
      viewMode: 2,
      aspectRatio: $image.width() / $image.height(),
      crop: function(event) {
        cropbox = event.detail // remember last crop - donesn't work
      },
         
    });
    cropper = $image.data('cropper');
    $("#close-zoom").on("click",() => {
      let img = cropper.getImageData()
      zoom = [(cropbox.x / img.naturalWidth).toFixed(3), (cropbox.y / img.naturalHeight).toFixed(3), (cropbox.width / img.naturalWidth).toFixed(3), (cropbox.height / img.naturalHeight).toFixed(3)]
      $("#zoom-result").val("zoom = [" + zoom + "]")      
    });
  
  });

  function connect(uri) {
    if (ws) {
      if (ws.connected) {
        return;
      }
    }
    var loc = window.location;
    if (uri == undefined) {
      // guess it's localhost
      var new_uri;
      if (loc.protocol === "https:") {
        new_uri = "wss:";
      } else {
        new_uri = "ws:";
      }
      new_uri += "//" + loc.host;
    } else {
      new_uri = uri;
    }
    toastr.info("Connecting to " + new_uri);
    ws = io(new_uri);

    ws.on("connect", function () {
      ws.emit("req-camera-config");
      ws.emit("req-mode");
      ws.emit("req-speed");
      ws.emit("req-camera-name");
      ws.emit("req-camera-ip");
    });

    ws.on("camera-config", msg =>editor.setValue(msg));

    ws.on("wpa-supplicant", msg => wifieditor.setValue(msg));

    ws.on("wpa-scan", function (msg) {
      let wifita = $("#wifi-textarea");
      wifita.val(wifita.val() + "WIFI SCAN\n");
      wifita.val(wifita.val() + msg);
      wifita.val(wifita.val() + "---\n");
       // autoscroll
       wifita.scrollTop(wifita[0].scrollHeight - wifita.height());
    });
    
    ws.on("mode", function (msg) {
      // Unfocus current button as we are getting the real value from server
      let ae = document.activeElement;
      ae.blur();
  
      toggle_active($("#camera-mode input"), tc(msg));     
    });

    ws.on("speed", function (msg) {
      // Unfocus current button as we are getting the real value from server
      let ae = document.activeElement;
      ae.blur();
  
      toggle_active($("#camera-speed input"), tc(msg));     
    });

    ws.on("message", msg =>  toastr.info(msg));
  
    ws.on("warning", msg => toastr.warning(msg));

    ws.on("latest-image-time", msg => toastr.info(msg));

    
    ws.on("latest-image-ago", msg => toastr.info(msg));

    ws.on("camera-name", msg => {
      $('#camera-name').text(msg);
      document.title = "TMV - " + msg
      $('#server').attr('href',TMV_SERVER + msg)
      
    });

    ws.on("files", function (msg) {
      let logta = $("#log-textarea");
      logta.val(logta.val() + "FILES\n");

      for (let f in msg) {
        logta.val(logta.val() + msg[f] + "\n");
      }
      logta.val(logta.val() + "---\n");

       // autoscroll
       logta.scrollTop(logta[0].scrollHeight - logta.height());
    });


    ws.on("n-files", function (msg) {
      toastr.info(msg + " files on-board")
    });

    ws.on("services-status", function (msg) {
      let logta = $("#log-textarea");
      logta.val(logta.val() + "SERVICES\n");
      Object.keys(msg).forEach(function (key) {
        logta.val(logta.val() + key + " : " + msg[key] + "\n");
      });
      logta.val(logta.val() + "---\n");
      // autoscroll
      logta.scrollTop(logta[0].scrollHeight - logta.height());
    });

    ws.on("journal", function (msg) {
      let logta = $("#log-textarea");
      logta.val(logta.val() + "JOURNAL\n");
      if ("journal" in msg) {
        logta.val(logta.val() + msg["journal"]);
        logta.val(logta.val() + "---\n");
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
      //toastr.info("Updated image")
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

function copyToClipboard(element) {
  var $temp = $("<input>");
  $("body").append($temp);
  $temp.val($(element).html()).select();
  document.execCommand("copy");
  $temp.remove();
 }