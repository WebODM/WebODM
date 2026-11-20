(function(){
  var html2canvas;
  var title = "";

  var takeScreenshot = function(el, ignore, onclone){
    return html2canvas(el, {
      allowTaint: true,
      useCORS: true,
      logging: false,
      onclone: onclone,
      removeContainer: false,
      ignoreElements: function(e){
        for (var i = 0; i < ignore.length; i++){
          if (e.classList.contains(ignore[i])) return true;
        }
        return false;
      }
    }).then(function(canvas) {
      var link = document.createElement('a');
      link.href = canvas.toDataURL();
      
      var filename = title.replace(/\s+/g, '-').replace(/\//g, '-').replace(/[^0-9a-zA-Z-_]+/g, '') + (title ? '-' : '') + "snapshot.png";
      filename = filename.replace(/-+/g, '-');

      link.download = filename;
      link.click();
    });
  }

  var registerApiActionButton = function(apiActionButton, getTitle, getContainer, ignore = [], onclone = function(doc){ return doc; }){
    apiActionButton([
      'snapshot/node_modules/html2canvas/dist/html2canvas.min.js'
    ], function(options, h2c){
      html2canvas = h2c;

      var btnRef = null;
      title = getTitle(options);

      var handleClick = function(){
        if (!btnRef) return;
        var icon = btnRef.querySelector("i");
        icon.className = "fa fa-circle-notch fa-spin";
        btnRef.disabled = true;
        
        takeScreenshot(getContainer(options), 
          ignore,
          onclone
        ).then(function(){
          icon.className = "fa fa-camera";
          btnRef.disabled = false;
        });
      };

      return React.createElement(
        "button",
        {
          type: "button",
          className: "btn btn-sm btn-secondary",
          title: "Take snapshot",
          style: {padding: "5px 9px"},
          ref: function(el){ btnRef = el; },
          onClick: handleClick
        },
        React.createElement("i", { className: "fa fa-camera" }, ""),
        ""
      );
    });
  }

  registerApiActionButton(PluginsAPI.Map.addActionButton, function(options){
      var mapTitle = options.map._container.parentElement.parentElement.parentElement.querySelector(".map-title");
      return mapTitle ? mapTitle.innerText.trim() : "";
    }, function(options){
      return options.map._container;
    },
    ["leaflet-popup-pane", "leaflet-control-container"],
    function(doc){
      var overlay = doc.querySelector(".leaflet-overlay-pane .leaflet-zoom-animated");
      if (!overlay) return doc;

      var match;
      if (overlay.style.transform.indexOf("translate3d") === 0) match = overlay.style.transform.match(/translate3d\((-?\d+)px,\s*(-?\d+)px/);
      else if (overlay.style.transform.indexOf("matrix") === 0) match = overlay.style.transform.match(/matrix\([\d\s,.-]+,\s*(-?\d+),\s*(-?\d+)\)/);

      if (match) {
        overlay.style.top = parseInt(match[2]) + "px";
        overlay.style.left = parseInt(match[1]) + "px";
        overlay.style.transform = "";
      }

      return doc;
    });
  registerApiActionButton(PluginsAPI.ModelView.addActionButton, function(options){
      var modelTitle = options.viewer.renderArea.closest(".model-view").querySelector(".model-title");
      return modelTitle ? modelTitle.innerText.trim() : "";
    }, function(options){
      return options.viewer.renderArea;
    },
    ["quick_buttons_container"]);
})();

