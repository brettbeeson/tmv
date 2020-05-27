"use strict";

let ws;
let rdws;
let lastImageUrl = "";
let lastStatusUpdate = 0;


$(document).ready(function () {
  var editor = ace.edit("editor");
  editor.setTheme("ace/theme/xcode");
  editor.setFontSize(20);
  editor.session.setMode("ace/mode/toml");

  toastr.options.preventDuplicates = true;
  toastr.options.positionClass = "toast-bottom-center";

  if ("WebSocket" in window) {
    connect();
  } else {
    alert("WebSocket NOT supported by your Browser!");
  }

  $("#refreshLastImage").on("click", updateLastImage);

  $("#reset").on("click", function (e) {
    if (ws) ws.send("restart",{});
    
  });

  //document.getElementById("logrefresh").addEventListener("click", logrefresh);

  function displayLastImage() {
    if (lastImageUrl) {
      document.getElementById("lastImage").src = lastImageUrl;
      document.getElementById("lastImageCaption").innerHTML = lastImageUrl;
    }
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
      ws.emit("camera-config");
      ws.emit("switch-status");
    });

    ws.on("log", function (msg) {
      $("#loglines").val(msg.lines);
      let logta = $("#logtext");
      logta.html(msg.log);
      if (logta.length) {
        logta.scrollTop(logta[0].scrollHeight - logta.height());
      }
    });

    ws.on("camera-config", function (msg) {
      toastr.info(msg.message);
      if (msg.success) {
        editor.setValue(msg.toml);
      }
    });

    ws.on("switch-status", function (msg) {
      toastr.info(msg.message);
      if (msg.success) {
        if ("camera" in msg) {
          toastr.warning("Camera : " + msg.camera);
          // change camera-{msg.camera} to active
        }
        if ("upload" in msg) {
          toastr.warning("Uploads : " + msg.upload);
          // change camera-{msg.camera} to active
        }
      }
    });

    ws.on("message", function (msg) {
      toastr.info(msg);
    });

    ws.on("close", function () {
      toastr.warning("Closed connection");
    });

    ws.on("error", function () {
      toastr.error("Connection error",setTimeout=0);
      // interface blank out?
    });
  }
});
