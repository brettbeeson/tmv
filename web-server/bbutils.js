/**
 * Return the last element in a path
 * eg. '/foo/bar/' => ''
 * * eg. '/foo/bar' => 'bar'
 * @param str
 * @returns {string}
 */
export function baseName(str) {
    let base = String(str).substring(str.lastIndexOf('/') + 1);
    if (base.lastIndexOf(".") !== -1)
        base = base.substring(0, base.lastIndexOf("."));
    return base;
}

/**
 * Return the directory element in a path
 * eg. '/foo/bar/' => 'bar'
 * * eg. '/foo/bar' => 'foo'
 * @param str
 * @returns {string}
 */
/*
export function parentDir(str) {
    // remove any filename at end
    let base = String(str).substring(str.lastIndexOf('/') + 1);
    // remove slash
    if (base.lastIndexOf("/") !== -1) {
        base = base.substring(0, base.lastIndexOf("/"));
    }
    // return last element
    return String(base).substring(str.lastIndexOf('/') + 1);
}
*/

/**
 * The ultimate split path.
 * Extracts dirname, filename, extension, and trailing URL params.
 * Correct handles:
 *   empty dirname,
 *   empty extension,
 *   random input (extracts as filename),
 *   multiple extensions (only extracts the last one),
 *   dotfiles (however, will extract extension if there is one)
 * @param  {string} path
 * @return {Object} Object containing fields "dirname", "filename", "extension", and "params"
 */
export function splitPath(path) {
    let result = path.replace(/\\/g, "/").match(/(.*\/)?(\..*?|.*?)(\.[^.]*?)?(#.*$|\?.*$|$)/);
    return {
        dirname: result[1] || "",
        filename: result[2] || "",
        extension: result[3] || "",
        params: result[4] || ""
    }
}

export function bytesToHumanReadable(sizeInBytes) {
    let i = -1;
    let units = [' kB', ' MB', ' GB'];
    do {
        sizeInBytes = sizeInBytes / 1024;
        i++;
    } while (sizeInBytes > 1024);
    return Math.max(sizeInBytes, 0.1).toFixed(1) + units[i];
}

/**
 *
 * @param slash
 * @returns {string} with or without an ending slash. Empty strings return "/" or "" respectively.
 * Multiple ending slashes are removed (if slash==false)
 */
String.prototype.slashEnd =  function (slash) {

    if (slash) {
        if (this.length === 0) return "/";
        if (this.endsWith("/")) {
            return String(this);
        } else {
            return this + "/";
        }
    } else {
        if (this.length === 0) return "";
        let i = this.length - 1;
        while (this[i] === '/') {
            i--;
            if (i === 0) return "";
        }
        return String(this.substr(0, i + 1 /* length, not index! */));
    }
};
/**
 *
 * @param slash
 * @returns {string} with or without a leading slash. Empty strings return "/" or "" respectively.
 * Multiple leading slashes are removed (if slash==false)
 */
String.prototype.slashStart = function (slash) {
    if (slash) {
        if (this.length === 0) return "/";
        if (this.startsWith("/")) {
            return String(this);
        } else {
            return "/" + this;
        }
    } else {
        if (this.length === 0) return "";
        let i = 0;
        while (this[i] === '/') {
            i++;
            if (i === this.length) return "";
        }
        return String(this.substr(i));
    }
};

/**
 *
 * @param slash
 * @returns {string} Filepath without the http://hostname:port part
 * http://foo.bar/this/that.html -> /this/that.html
 *  * http://foo.bar/that.html -> /that.html
 */
String.prototype.rootRel = function () {
    return this.replace(location.origin,"");
};
