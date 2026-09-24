/*
 * Lets the same page run in two places without forking it.
 *
 * The UI asks for capabilities through claude.use(name). Hosted, the platform
 * provides them. Installed, this provides them against the local app's own API:
 * storage is JSON files on this computer, drafting goes to whichever assistant
 * the family chose, and a download is just a download.
 *
 * Load before the UI script.
 */
(function () {
  "use strict";

  var API = "";

  function json(method, path, body) {
    return fetch(API + path, {
      method: method,
      headers: body ? { "content-type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined
    }).then(function (r) {
      return r.json().then(function (d) { return { status: r.status, body: d }; },
                           function () { return { status: r.status, body: {} }; });
    });
  }

  /* ---- storage ------------------------------------------------------- */

  function snapDoc(id, data) {
    return { id: id, exists: data !== undefined && data !== null, data: function () { return data; },
             metadata: { fromCache: false, hasPendingWrites: false } };
  }

  var POLL_MS = 3000;

  function makeDb() {
    var watchers = [];

    function poll() {
      var seen = {};
      watchers.forEach(function (w) { seen[w.collection] = true; });
      Object.keys(seen).forEach(function (c) {
        json("GET", "/api/db/" + c).then(function (res) {
          var docs = (res.body && res.body.docs) || {};
          var serial = JSON.stringify(docs);
          watchers.filter(function (w) { return w.collection === c; }).forEach(function (w) {
            if (w.last === serial) return;
            w.last = serial;
            if (w.docId) {
              w.next(snapDoc(w.docId, docs[w.docId]));
            } else {
              w.next({
                docs: Object.keys(docs).map(function (k) { return snapDoc(k, docs[k]); }),
                size: Object.keys(docs).length,
                empty: !Object.keys(docs).length,
                docChanges: function () { return []; },
                metadata: { fromCache: false, hasPendingWrites: false }
              });
            }
          });
        });
      });
    }
    setInterval(poll, POLL_MS);

    function watch(collection, docId, next) {
      var w = { collection: collection, docId: docId, next: next, last: null };
      watchers.push(w);
      setTimeout(poll, 0);
      return function () { watchers = watchers.filter(function (x) { return x !== w; }); };
    }

    function touch(collection) {
      watchers.forEach(function (w) { if (w.collection === collection) w.last = null; });
      setTimeout(poll, 60);
    }

    return {
      collection: function (path) {
        return {
          path: path,
          onSnapshot: function (next) { return watch(path, null, next); },
          doc: function (id) { return docRef(path + "/" + id); }
        };
      },
      doc: function (path) { return docRef(path); }
    };

    function docRef(path) {
      var parts = path.split("/");
      var collection = parts[0], id = parts.slice(1).join("-");
      return {
        id: id,
        path: path,
        get: function () {
          return json("GET", "/api/db/" + collection).then(function (r) {
            return snapDoc(id, ((r.body && r.body.docs) || {})[id]);
          });
        },
        set: function (data) {
          return json("PUT", "/api/db/" + collection + "/" + encodeURIComponent(id), { data: data })
            .then(function (r) {
              if (r.status >= 400) throw { code: "unavailable", message: "Could not save." };
              touch(collection);
            });
        },
        update: function (data) { return this.set(data); },
        delete: function () {
          return json("DELETE", "/api/db/" + collection + "/" + encodeURIComponent(id))
            .then(function () { touch(collection); });
        },
        onSnapshot: function (next) { return watch(collection, id, next); }
      };
    }
  }

  /* ---- drafting ------------------------------------------------------ */

  function makeSample() {
    function ask(input) {
      var prompt = typeof input === "string"
        ? input
        : input.map(function (t) { return t.content; }).join("\n\n");
      return json("POST", "/api/llm/json", { prompt: prompt }).then(function (r) {
        if (r.status === 409) throw { code: "not_granted", message: r.body.message };
        if (r.status >= 400) throw { code: "provider_error", message: r.body.message, hint: r.body.hint };
        return r.body.data;
      });
    }
    var fn = function (input) {
      return ask(input).then(function (d) { return { text: JSON.stringify(d), truncated: false }; });
    };
    fn.json = function (input) { return ask(input); };
    fn.limits = function () { return Promise.resolve({ images: null }); };
    return fn;
  }

  /* ---- downloads ----------------------------------------------------- */

  function makeDownloads() {
    return {
      save: function (req) {
        var blob = req.data instanceof Blob ? req.data : new Blob([req.data], { type: "text/plain" });
        var url = URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = url; a.download = req.filename || "download.txt";
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
        return Promise.resolve({ status: "saved" });
      }
    };
  }

  var db = null, sample = null, downloads = null;

  window.claude = {
    use: function (name) {
      if (name === "db") { db = db || makeDb(); return Promise.resolve(db); }
      if (name === "sample") { sample = sample || makeSample(); return Promise.resolve(sample); }
      if (name === "downloads") { downloads = downloads || makeDownloads(); return Promise.resolve(downloads); }
      return Promise.resolve(null);
    },
    local: true
  };
})();
