"use strict";

const TMV_SERVER = "http://home.brettbeeson.com.au/"

let ws;
let current_mode='on';      // camera mode, set on receipt of 'mode' message

// Set mode from string or href/object 
// (The server will broadcast a mode update so expect that)
function mode(e) {
  let position 
  if (typeof(e) == 'string') {
    position = e;
  } else {
    position = e.target.value;
  }
  ws.emit("mode",  position );
}

function speed(e) {
  let position = e.target.value;
  ws.emit("speed", position );
}

function set_video_src() {
  $("#video-img").removeAttr("src");
  let loc = new URL(window.location); // current url
  let video_src = loc.protocol + "//" + loc.hostname + ":5001" + "/video"
  $("#video-img").attr('src',video_src);
  
}

//function reload_video_src(e) {
//  setTimeout(set_video_src,1000,e);
//}

$(document).ready(function () {

  $("#video-img").removeAttr("src");
  // todo: automate this button on load-img fail
//$("#video-img").on("error", alert("fail!")); //() => reload_video_src(this));
  $("#video-reload").on("click", () => set_video_src() )

  $("time.timeago").timeago(); //https://github.com/rmm5t/jquery-timeago

  var editor = ace.edit("editor");
  editor.setTheme("ace/theme/xcode");
  editor.setFontSize(16);
  editor.session.setMode("ace/mode/toml");

  var wifieditor = ace.edit("wifieditor");
  wifieditor.setTheme("ace/theme/xcode");
  wifieditor.setFontSize(16);
    
  $("#pj-status").on("click",  () =>  ws.emit("req-pj-status"));

  toastr.options.positionClass = "toast-bottom-center";

  if ("WebSocket" in window) {
    //connect("ws://localhost:5000");
    connect();
  } else {
    alert("WebSockets are NOT supported by your browser!");
  }

  $("#server").on("click", function() {
    // force open in new tab
    // set via camera_name
    let server = $("#server").attr("href");    
      window.open(server,"_blank");
  });
  

  // on video tab click, shift to video mode
  $('#pills-video-tab').on('click', function (e) {
    e.preventDefault()
    mode('video'); 
  })
  // upon home-tab click, return to 'camera' mode (on)
  $('#pills-home-tab').on('click', function (e) {
    e.preventDefault()
    mode('on'); 
  })
     
  $("#services").on("click",  () =>     ws.emit("req-services-status"));
  
  $("#journal").on("click",  () =>     ws.emit("req-journal"));

  $("#files").on("click", () =>  ws.emit("req-files"));
  
  $("#error").on("click", () => ws.emit("raise-error"));
  
  $("#latest-image-time").on("click", () => ws.emit("req-latest-image-time"));
  
  $("#restart").on("click", () =>  ws.emit("restart-camera"));
  
  $("#saveandrestart").on("click", function () {
    ws.emit("camera-config", editor.getValue());
    ws.emit("restart-camera");
  });

  $("#wifi-save").on("click", () =>  ws.emit("wpa-supplicant", wifieditor.getValue()));
  

  $("#wifi-scan").on("click", () => ws.emit("req-wpa-scan"));

  $("#wifi-info").on("click", () => ws.emit("req-network-info"));
  
  $("#wifi-cancel").on("click",  () => ws.emit("req-wpa-supplicant"));
  
  $("#wifi-reconfigure").on("click", () =>ws.emit("wpa-reconfigure"));
  
  $("#camera-mode input").on("click", mode);

  $("#camera-speed  input").on("click", speed);

  $("#save").on("click", () =>  ws.emit("camera-config", editor.getValue()));
  
  $("#cancel").on("click", () =>  ws.emit("cancel-shutdown"));

  $("#reload").on("click", () => ws.emit("req-camera-config"));

  $("#about").on("click", () => {
    ws.emit("req-camera-ip")
  });
    
  $("#restart-hw").on("click", () => ws.emit("restart-hw"));
  
  $("#shutdown-hw").on("click", () => ws.emit("shutdown-hw"));

  $("#cancel-shutdown").on("click", () => ws.emit("cancel-shutdown"));
  
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
    ws = io(new_uri);

    ws.on("connect", function () {
      ws.emit("req-camera-config");
      ws.emit("req-mode");
      ws.emit("req-speed");
      ws.emit("req-camera-name");
      ws.emit("req-camera-interval");
      ws.emit("req-image");
    });

    ws.on("pj-status", json => {
      append_to_textarea($("#log-textarea"),"PIJUICE INFO",JSON.stringify(json, undefined, 4));
      $("#pj-battery-status").text(json.battery)
      $("#pj-battery-level").text("Battery: " + json.chargeLevel + "%")
      
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
    
    ws.on("wpa-supplicant", msg => wifieditor.setValue(msg));

    ws.on("network-info", function (msg) {
      append_to_textarea($("#wifi-textarea"),"NETWORK INFO",msg);
    });
    
    ws.on("camera-interval", function (msg) {
      $("#camera-interval").text("Interval: " + msg + "s")
    });
    

    ws.on("mode", function (msg) {
      // Unfocus current button as we are getting the real value from server
      let ae = document.activeElement;
      ae.blur();
      toggle_active($("#camera-mode input"), tc(msg));     
      ws.emit("req-camera-interval");
      
      if (msg !='video' && current_mode=="video") {
        // we're in video mode: exit it
        $("#video-img").removeAttr("src");
        $('#pills-home-tab').tab('show'); 
      }
      if (msg=='video' && current_mode!='video') {
        // move to video mode
        set_video_src()
        $('#pills-video-tab').tab('show'); 
      }
      current_mode = msg
    });

    ws.on("speed", function (msg) {
      // Unfocus current button as we are getting the real value from server
      let ae = document.activeElement;
      ae.blur();
      toggle_active($("#camera-speed input"), tc(msg));     
      ws.emit("req-camera-interval");
    });

    ws.on("message", msg =>  toastr.info(msg));
  
    ws.on("warning", msg => toastr.warning(msg));

    ws.on("latest-image-time", msg => {
      let dt = strftime("%Y-%m-%d %H:%M:%S",msg)
      $("#latest-image-time").text(dt);
      $("#latest-image-ago").timeago("update",msg);
      $("#latest-image-ago").text($("#latest-image-ago").text());
      $('#new-image-indicator').css("visibility", "visible");
      setTimeout(function () {
       $('#new-image-indicator').css("visibility", "hidden");
      }, 2000);
      
    });

    ws.on("camera-name", msg => {
      $('#camera-name').text(msg);
      document.title = "TMV - " + msg
      $('#server').attr('href',TMV_SERVER + msg)
    });

    ws.on("files", function (msg) {
      let fs = ""
      for (let f in msg) {
        fs = fs + msg[f] + "\n"
      }
      fs = fs + "Total: " + msg.length
      append_to_textarea($("#log-textarea"),"FILES",fs);

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

    ws.on("camera-ip", function (msg) {
      append_to_textarea($("#log-textarea"),"CAMERA IP",msg);
    });
    
    ws.on("journal", function (msg) {
      append_to_textarea($("#log-textarea"),"JOURNAL",msg);
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
      ws.emit("req-latest-image-time") // ask the date and hanlders will displayu it
      
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

// Title Case
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


function append_to_textarea(textarea, title, msg) {
  textarea.val(textarea.val() + "vvv " + title + " vvv\n");
  textarea.val(textarea.val() + msg);
  textarea.val(textarea.val() + "\n^^^ " + title + " ^^^\n");
  // autoscroll
  textarea.scrollTop(textarea[0].scrollHeight - textarea.height());
  }
  