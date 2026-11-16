import os
import uuid

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint, or_
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY", "local-development-only-change-this"
)
os.makedirs(app.instance_path, exist_ok=True)

database_path = os.environ.get(
    "DATABASE_PATH",
    os.path.join(app.instance_path, "socially.db")
)

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + database_path

app.config["UPLOAD_FOLDER"] = os.environ.get(
    "UPLOAD_FOLDER",
    os.path.join(app.root_path, "static", "uploads")
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

db = SQLAlchemy(app)

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(30), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    bio = db.Column(db.String(160), default="")
    avatar = db.Column(db.String(255), default="")


class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    caption = db.Column(db.String(500), nullable=False, default="")
    image = db.Column(db.String(255), nullable=False)
    media_type = db.Column(db.String(10), nullable=False, default="photo")
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    user = db.relationship("User")
    likes = db.relationship("Like", backref="post", lazy=True)
    comments = db.relationship("Comment", backref="post", lazy=True)


class Like(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "post_id", name="unique_user_like"),
    )


class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.String(300), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=False)

    user = db.relationship("User")


class Follow(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    follower_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    followed_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    __table_args__ = (
        UniqueConstraint("follower_id", "followed_id", name="unique_follow"),
    )



class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    content = db.Column(db.String(1000), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sender = db.relationship("User", foreign_keys=[sender_id])
    receiver = db.relationship("User", foreign_keys=[receiver_id])



def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def get_logged_in_user():
    if "user_id" not in session:
        return None

    user = db.session.get(User, session["user_id"])

    if not user:
        session.clear()

    return user


@app.route("/")
def home():
    user = get_logged_in_user()

    if not user:
        return redirect(url_for("login"))

    posts = Post.query.order_by(Post.id.desc()).all()

    liked_ids = {
        like.post_id
        for like in Like.query.filter_by(user_id=user.id).all()
    }

    return render_template(
        "index.html",
        user=user,
        posts=posts,
        liked_ids=liked_ids
    )


@app.route("/comments/<int:post_id>")
def comments(post_id):
    user = get_logged_in_user()
    if not user:
        return redirect(url_for("login"))

    post = db.session.get(Post, post_id)
    if not post:
        return redirect(url_for("home"))

    return render_template("comments.html", post=post, user=user)


@app.route("/profile/<username>")
def profile(username):
    user = get_logged_in_user()

    if not user:
        return redirect(url_for("login"))

    profile_user = User.query.filter_by(
        username=username.lower()
    ).first_or_404()

    posts = Post.query.filter_by(
        user_id=profile_user.id
    ).order_by(Post.id.desc()).all()

    follower_count = Follow.query.filter_by(
        followed_id=profile_user.id
    ).count()

    following_count = Follow.query.filter_by(
        follower_id=profile_user.id
    ).count()

    is_following = Follow.query.filter_by(
        follower_id=user.id,
        followed_id=profile_user.id
    ).first() is not None

    return render_template(
        "profile.html",
        user=user,
        profile=profile_user,
        profile_user=profile_user,
        posts=posts,
        follower_count=follower_count,
        followers_count=follower_count,
        following_count=following_count,
        is_following=is_following
    )


@app.route("/follow/<int:user_id>", methods=["POST"])
def follow(user_id):
    user = get_logged_in_user()

    if not user:
        return redirect(url_for("login"))

    target = db.session.get(User, user_id)

    if not target:
        flash("User not found.")
        return redirect(url_for("home"))

    if target.id == user.id:
        flash("You cannot follow yourself.")
        return redirect(url_for("profile", username=target.username))

    existing = Follow.query.filter_by(
        follower_id=user.id,
        followed_id=target.id
    ).first()

    if existing:
        db.session.delete(existing)
    else:
        db.session.add(Follow(
            follower_id=user.id,
            followed_id=target.id
        ))

    db.session.commit()

    return redirect(url_for("profile", username=target.username))


@app.route("/register", methods=["GET", "POST"])
def register():
    error = None

    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")

        if not username or not password:
            error = "Please fill in every field."
        elif len(username) < 3 or len(username) > 30:
            error = "Username must be 3-30 characters."
        elif len(password) < 8:
            error = "Password must be at least 8 characters."
        elif User.query.filter_by(username=username).first():
            error = "That username is already taken."
        else:
            user = User(
                username=username,
                password=generate_password_hash(password)
            )
            db.session.add(user)
            db.session.commit()
            session["user_id"] = user.id
            return redirect(url_for("home"))

    return render_template("auth.html", mode="register", error=error)


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")

        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password, password):
            session["user_id"] = user.id
            return redirect(url_for("home"))

        error = "Incorrect username or password."

    return render_template("auth.html", mode="login", error=error)


@app.route("/upload", methods=["POST"])
def upload():
    user = get_logged_in_user()

    if not user:
        return redirect(url_for("login"))

    media = request.files.get("image")
    caption = request.form.get("caption", "").strip()
    media_type = request.form.get("media_type", "photo").strip().lower()

    if media_type not in {"photo", "video", "reel"}:
        flash("Invalid media type.")
        return redirect(url_for("create"))

    if not media or not media.filename:
        flash("Please select a file.")
        return redirect(url_for("create"))

    original_name = secure_filename(media.filename)

    if "." not in original_name:
        flash("Invalid filename.")
        return redirect(url_for("create"))

    extension = original_name.rsplit(".", 1)[1].lower()

    image_extensions = {"jpg", "jpeg", "png", "webp"}
    video_extensions = {"mp4", "webm"}

    if media_type == "photo" and extension not in image_extensions:
        flash("Photos must be JPG, JPEG, PNG or WEBP.")
        return redirect(url_for("create"))

    if media_type in {"video", "reel"} and extension not in video_extensions:
        flash("Videos and Reels must be MP4 or WEBM.")
        return redirect(url_for("create"))

    if len(caption) > 500:
        flash("Caption is too long.")
        return redirect(url_for("create"))

    filename = f"{uuid.uuid4().hex}.{extension}"

    upload_folder = app.config["UPLOAD_FOLDER"]
    os.makedirs(upload_folder, exist_ok=True)

    media.save(os.path.join(upload_folder, filename))

    post = Post(
        caption=caption,
        image=filename,
        media_type=media_type,
        user_id=user.id
    )

    db.session.add(post)
    db.session.commit()

    flash("Your post was published!")
    return redirect(url_for("home"))


@app.route("/like/<int:post_id>", methods=["POST"])
def like(post_id):
    user = get_logged_in_user()

    if not user:
        return {"error": "Login required"}, 401

    post = db.session.get(Post, post_id)

    if not post:
        return {"error": "Post not found"}, 404

    existing = Like.query.filter_by(
        user_id=user.id,
        post_id=post_id
    ).first()

    if existing:
        db.session.delete(existing)
        liked = False
    else:
        db.session.add(Like(user_id=user.id, post_id=post_id))
        liked = True

    db.session.commit()

    return {
        "liked": liked,
        "likes_count": Like.query.filter_by(post_id=post_id).count()
    }


@app.route("/comment/<int:post_id>", methods=["POST"])
def comment(post_id):
    user = get_logged_in_user()
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if not user:
        if is_ajax:
            return {"error": "Please log in first."}, 401
        return redirect(url_for("login"))

    post = db.session.get(Post, post_id)

    if not post:
        if is_ajax:
            return {"error": "Post not found."}, 404
        flash("Post not found.")
        return redirect(url_for("home"))

    content = request.form.get("content", "").strip()

    if not content:
        return {"error": "Comment cannot be empty."}, 400

    if len(content) > 300:
        return {"error": "Comment must be 300 characters or less."}, 400

    new_comment = Comment(
        content=content,
        user_id=user.id,
        post_id=post_id
    )

    db.session.add(new_comment)
    db.session.commit()

    if is_ajax:
        return {
            "success": True,
            "username": user.username,
            "content": new_comment.content
        }

    return redirect(url_for("home"))


@app.route("/edit-profile", methods=["GET", "POST"])
def edit_profile():
    user = get_logged_in_user()

    if not user:
        return redirect(url_for("login"))

    if request.method == "POST":
        bio = request.form.get("bio", "").strip()
        avatar = request.files.get("avatar")

        if len(bio) > 160:
            flash("Bio must be 160 characters or less.")
            return redirect(url_for("edit_profile"))

        if avatar and avatar.filename:
            if not allowed_file(avatar.filename):
                flash("Use JPG, JPEG, PNG or WEBP.")
                return redirect(url_for("edit_profile"))

            original = secure_filename(avatar.filename)

            if "." not in original:
                flash("Invalid image filename.")
                return redirect(url_for("edit_profile"))

            extension = original.rsplit(".", 1)[1].lower()
            filename = f"{uuid.uuid4().hex}.{extension}"

            upload_folder = app.config["UPLOAD_FOLDER"]
            os.makedirs(upload_folder, exist_ok=True)

            avatar.save(os.path.join(upload_folder, filename))
            user.avatar = filename

        user.bio = bio
        db.session.commit()

        flash("Profile updated successfully!")
        return redirect(url_for("profile", username=user.username))

    return render_template("edit_profile.html", user=user)



@app.route("/messages")
def messages():
    user = get_logged_in_user()

    if not user:
        return redirect(url_for("login"))

    people = User.query.filter(User.id != user.id).all()
    conversations = []

    for person in people:
        latest = Message.query.filter(
            or_(
                (Message.sender_id == user.id) & (Message.receiver_id == person.id),
                (Message.sender_id == person.id) & (Message.receiver_id == user.id)
            )
        ).order_by(Message.created_at.desc()).first()

        if latest:
            conversations.append((person, latest))

    return render_template(
        "messages.html",
        user=user,
        conversations=conversations,
        people=people
    )


@app.route("/chat/<username>", methods=["GET", "POST"])
def chat(username):
    user = get_logged_in_user()

    if not user:
        return redirect(url_for("login"))

    other = User.query.filter_by(username=username.lower()).first_or_404()

    if other.id == user.id:
        flash("You cannot message yourself.")
        return redirect(url_for("messages"))

    if request.method == "POST":
        content = request.form.get("content", "").strip()

        if not content:
            flash("Message cannot be empty.")
        elif len(content) > 1000:
            flash("Message is too long.")
        else:
            new_message = Message(
                sender_id=user.id,
                receiver_id=other.id,
                content=content
            )
            db.session.add(new_message)
            db.session.commit()

        return redirect(url_for("chat", username=other.username))

    conversation = Message.query.filter(
        or_(
            (Message.sender_id == user.id) & (Message.receiver_id == other.id),
            (Message.sender_id == other.id) & (Message.receiver_id == user.id)
        )
    ).order_by(Message.created_at.asc()).all()

    return render_template(
        "chat.html",
        user=user,
        other=other,
        conversation=conversation
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


with app.app_context():
    db.create_all()

    from sqlalchemy import inspect

    post_columns = {
        column["name"]
        for column in inspect(db.engine).get_columns("post")
    }

    if "media_type" not in post_columns:
        db.session.execute(
            db.text(
                "ALTER TABLE post ADD COLUMN media_type "
                "VARCHAR(10) NOT NULL DEFAULT 'photo'"
            )
        )

    columns = {
        column["name"]
        for column in inspect(db.engine).get_columns("user")
    }

    if "bio" not in columns:
        db.session.execute(
            db.text("ALTER TABLE user ADD COLUMN bio VARCHAR(160) DEFAULT ''")
        )

    if "avatar" not in columns:
        db.session.execute(
            db.text("ALTER TABLE user ADD COLUMN avatar VARCHAR(255) DEFAULT ''")
        )

    db.session.commit()




@app.route("/search")
def search():
    user = get_logged_in_user()
    if not user:
        return redirect(url_for("login"))

    query = request.args.get("q", "").strip()[:100]
    users = []
    posts = []

    if query:
        users = User.query.filter(
            User.username.ilike(f"%{query}%")
        ).order_by(User.username).limit(30).all()

        posts = Post.query.filter(
            Post.caption.ilike(f"%{query}%")
        ).order_by(Post.id.desc()).limit(30).all()

    return render_template(
        "search.html",
        user=user,
        query=query,
        users=users,
        posts=posts
    )



@app.route("/reels")
def reels():
    user = get_logged_in_user()

    if not user:
        return redirect(url_for("login"))

    posts = Post.query.filter_by(
        media_type="reel"
    ).order_by(Post.id.desc()).all()

    liked_ids = {
        like.post_id
        for like in Like.query.filter_by(user_id=user.id).all()
    }

    return render_template(
        "reels.html",
        user=user,
        posts=posts,
        liked_ids=liked_ids
    )


@app.route("/create")
def create():
    user = get_logged_in_user()

    if not user:
        return redirect(url_for("login"))

    return render_template("create.html", user=user)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
