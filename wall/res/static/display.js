/*
 * Wall
 */

wall.display = {};
(function(ns) {

/* ==== DisplayUi ==== */

ns.DisplayUi = function(bricks) {
    wall.Ui.call(this, bricks);
    this._postSpace = null;

    this.addPostElementType(ns.TextPostElement);
    this.addPostElementType(ns.ImagePostElement);
    this.addEventListener("posted", this._posted.bind(this));

    this.loadBricks(bricks, "DisplayBrick");

    this._postSpace = new ns.PostSpace(this);
    document.body.appendChild(this._postSpace.element);
    this._postSpace.attachedCallback();
};

ns.DisplayUi.prototype = Object.create(wall.Ui.prototype, {
    _posted: {value: function(event) {
        this._postSpace.post = event.args.post;
    }}
});

/* ==== PostElement ==== */

ns.PostElement = function(post, ui) {
    wall.PostElement.call(this, post, ui);

    this.content = document.createElement("div");
    this.content.classList.add("post-content");
    this.content.classList.add(wall.hyphenate(this.postType) + "-content");

    this.element = document.createElement("iframe");
    this.element.classList.add("post");
    this.element.classList.add(wall.hyphenate(this.postType));

    $(this.element).one("load", function(event) {
        this.element.contentDocument.body.appendChild(this.content);
        this.contentAttachedCallback();
    }.bind(this));
    this.element.src = "/display/post";
};

ns.PostElement.prototype = Object.create(wall.PostElement.prototype, {
    contentAttachedCallback: {value: function() {}}
});

/* ==== TextPostElement ==== */

ns.TextPostElement = function(post, ui) {
    ns.PostElement.call(this, post, ui);
    var pre = document.createElement("pre");
    pre.textContent = this.post.content;
    this.content.appendChild(pre);
};

ns.TextPostElement.prototype = Object.create(ns.PostElement.prototype, {
    postType: {value: "TextPost"},

    contentAttachedCallback: {value: function() {
        // First layout the text by rendering it (with a fixed font size) into
        // an element with a fixed maximum width. Then fit this element to the
        // post element (scaling the text accordingly).
        var pre = this.content.querySelector("pre");
        pre.style.fontSize = "16px";
        pre.style.maxWidth = "70ch";
        $(pre).fitToParent({maxFontSize: (20 / 1.5) + "vh"});
    }}
});

/* ==== ImagePostElement ==== */

ns.ImagePostElement = function(post, ui) {
    ns.PostElement.call(this, post, ui);
    this.content.style.backgroundImage = "url(" + this.post.url + ")";
};

ns.ImagePostElement.prototype = Object.create(ns.PostElement.prototype, {
    postType: {value: "ImagePost"}
});

/* ==== PostSpace ==== */

ns.PostSpace = function(ui) {
    wall.Element.call(this, ui);
    this._post = null;
    this._postElement = null;
    this.element = document.createElement("div");
    this.element.classList.add("post-space");
};

/**
 * Space for a `PostElement`.
 *
 * Attributes:
 *
 *  - post: post for which the `PostSpace` holds a `PostElement` or `null` if
 *    the `PostSpace` is currently empty. Setting this constructs a
 *    `PostElement` inside the `PostSpace` or empties the `PostSpace` if the
 *    value is `null`.
 */
ns.PostSpace.prototype = Object.create(wall.Element.prototype, {
    post: {
        set: function(value) {
            if (this._post) {
                this.element.removeChild(this._postElement.element);
                this._postElement.detachedCallback();
                this._postElement = null;
                this._post = null;
            }

            this._post = value;

            if (this._post) {
                var postElementType =
                    this.ui.postElementTypes[this._post.__type__];
                this._postElement = new postElementType(this._post, this.ui);
                this.element.appendChild(this._postElement.element);
                this._postElement.attachedCallback();
            }
        },
        get: function() {
            return this._post;
        }
    }
});

}(wall.display));
