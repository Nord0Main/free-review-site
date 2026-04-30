import os
from flask import Flask, jsonify, render_template, request, redirect, url_for, session
from supabase import create_client, Client
from dotenv import load_dotenv
from better_profanity import profanity

# Load environment variables from the .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = "super_secret_nord_key_for_testing"

# Initialize Supabase client
url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")

if not url or not key:
    raise ValueError("Supabase credentials not found. Check your .env file.")

supabase: Client = create_client(url, key)

# Load the default bad word dictionary into memory
profanity.load_censor_words()

# Helper function to safely censor text
def safe_censor(text):
    if not text:
        return ""
    return profanity.censor(text)

# NEW: The Leveling Engine
def update_user_level(user_id):
    try:
        user = supabase.table('users').select('vote_count, approved_suggestions').eq('id', user_id).single().execute()
        votes = user.data.get('vote_count', 0)
        suggestions = user.data.get('approved_suggestions', 0)
        
        # Calculate XP
        xp = (votes * 10) + (suggestions * 50)
        level = (xp // 100) + 1
        
        # Determine Rank Title
        if level < 5: rank = "Novice"
        elif level < 10: rank = "Critic"
        elif level < 20: rank = "Curator"
        elif level < 30: rank = "Tastemaker"
        else: rank = "Grandmaster"
        
        # Save to database
        supabase.table('users').update({
            "xp": xp, "level": level, "rank_name": rank
        }).eq('id', user_id).execute()
    except Exception as e:
        print(f"Leveling Error: {e}")

# --- START HIGHLIGHTING & COPYING HERE ---

@app.route('/')
def home():
    current_user_id = session.get('user_id')
    user_role, username, profile_image_url, needs_tos, user_level, text_size = None, None, None, False, 1, 'medium'
    
    if current_user_id:
        try:
            response = supabase.table('users').select('role, username, profile_image_url, agreed_to_tos, level, text_size').eq('id', current_user_id).single().execute()
            user_data = response.data
            user_role = user_data.get('role', 'user')
            username = user_data.get('username')
            profile_image_url = user_data.get('profile_image_url')
            user_level = user_data.get('level', 1)
            text_size = user_data.get('text_size', 'medium')
            needs_tos = not user_data.get('agreed_to_tos', False)
        except: pass

    # NEW: Fetch ALL reviews (including drafts for 'Coming Soon' placeholders)
    try:
        res = supabase.table('reviews').select('title, slug, category, staff_score, community_score, cover_image_url, release_year, status').order('created_at', desc=True).execute()
        reviews = res.data if res.data else []
    except Exception as e:
        reviews = []
        print(f"Error fetching reviews: {e}")
            
    return render_template('index.html', user_id=current_user_id, user_role=user_role,
                           username=username, profile_image_url=profile_image_url,
                           user_level=user_level, text_size=text_size, needs_tos=needs_tos,
                           reviews=reviews) # <-- We now pass the reviews to the frontend!

# --- LEGAL ROUTES ---
@app.route('/tos')
def tos():
    return render_template('tos.html')

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

# --- AUTHENTICATION & PROFILE ROUTES ---

# --- STOP HIGHLIGHTING & COPYING HERE ---

# --- AUTHENTICATION & PROFILE ROUTES ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        try:
            response = supabase.auth.sign_in_with_password({"email": email, "password": password})
            session['user_id'] = response.user.id
            return redirect(url_for('home'))
        except Exception as e:
            return render_template('login.html', error="Invalid email or password.")
            
    return render_template('login.html')

@app.route('/signup', methods=['POST'])
def signup():
    email = request.form.get('email')
    password = request.form.get('password')
    username = safe_censor(request.form.get('username'))
    try:
        response = supabase.auth.sign_up({"email": email, "password": password})
        user_id = response.user.id
        
        supabase.table('users').insert({
            "id": user_id,
            "email": email,
            "username": username
        }).execute()
        
        session['user_id'] = user_id
        return redirect(url_for('home'))
    except Exception as e:
        return render_template('login.html', error=str(e))

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    supabase.auth.sign_out()
    return redirect(url_for('home'))

@app.route('/profile')
def profile():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    try:
        response = supabase.table('users').select('*').eq('id', user_id).single().execute()
        return render_template('profile.html', user=response.data)
    except Exception as e:
        return f"Error loading profile: {e}"

@app.route('/user/<target_username>')
def public_profile(target_username):
    # 1. Find the user they are looking for
    try:
        user_res = supabase.table('users').select('*').eq('username', target_username).single().execute()
        target_user = user_res.data
    except Exception:
        return "User not found.", 404

    # 2. Find all published reviews written by this user
    try:
        reviews_res = supabase.table('reviews').select('*, users(username, profile_image_url, level)').eq('author_id', target_user['id']).eq('status', 'published').order('created_at', desc=True).execute()
        user_reviews = reviews_res.data
    except Exception:
        user_reviews = []

    # 3. Figure out who is currently viewing the page (for the top nav and mature filter)
    current_user_id = session.get('user_id')
    viewer_role, viewer_username, viewer_avatar, viewer_level, show_mature = 'guest', None, None, 1, False
    
    if current_user_id:
        try:
            viewer_res = supabase.table('users').select('role, username, profile_image_url, level, show_mature').eq('id', current_user_id).single().execute()
            viewer_role = viewer_res.data.get('role', 'user')
            viewer_username = viewer_res.data.get('username')
            viewer_avatar = viewer_res.data.get('profile_image_url')
            viewer_level = viewer_res.data.get('level', 1)
            show_mature = viewer_res.data.get('show_mature', False)
        except: pass

    # 4. Filter out mature content if the viewer hasn't opted in
    if not show_mature and viewer_role not in ['owner', 'admin']:
        safe_reviews = []
        mature_tags = ['nsfw', '18+', 'mature']
        for r in user_reviews:
            r_tags = r.get('tags') or []
            if not any(t in r_tags for t in mature_tags):
                safe_reviews.append(r)
        user_reviews = safe_reviews

    return render_template('user_profile.html', 
                           target_user=target_user, 
                           reviews=user_reviews,
                           user_id=current_user_id,
                           user_role=viewer_role,
                           username=viewer_username,
                           profile_image_url=viewer_avatar,
                           user_level=viewer_level)

@app.route('/update-username', methods=['POST'])
def update_username():
    user_id = session.get('user_id')
    if not user_id: return redirect(url_for('login'))
    
    new_username = safe_censor(request.form.get('new_username'))
    user = supabase.table('users').select('has_changed_name').eq('id', user_id).single().execute()
    
    if not user.data['has_changed_name']:
        supabase.table('users').update({
            "username": new_username,
            "has_changed_name": True
        }).eq('id', user_id).execute()
        
    return redirect(url_for('profile'))

@app.route('/update-favorites', methods=['POST'])
def update_favorites():
    user_id = session.get('user_id')
    if not user_id: return redirect(url_for('login'))
    
    games_input = safe_censor(request.form.get('top_games', ''))
    movies_input = safe_censor(request.form.get('top_movies', ''))
    
    games = [item.strip().lower() for item in games_input.split(',') if item.strip()]
    movies = [item.strip().lower() for item in movies_input.split(',') if item.strip()]
    
    all_tags = games + movies
    
    for tag in all_tags:
        try: supabase.table('tags').insert({"name": tag}).execute()
        except: pass 
    
    supabase.table('users').update({
        "top_games": games,
        "top_movies": movies
    }).eq('id', user_id).execute()
    
    return redirect(url_for('profile'))

@app.route('/update-profile-image', methods=['POST'])
def update_profile_image():
    user_id = session.get('user_id')
    if not user_id: return redirect(url_for('login'))
    
    new_image_url = request.form.get('profile_image_url')
    
    try:
        supabase.table('users').update({
            "profile_image_url": new_image_url
        }).eq('id', user_id).execute()
        return redirect(url_for('profile'))
    except Exception as e:
        return f"Error updating profile image: {e}"

@app.route('/update-settings', methods=['POST'])
def update_settings():
    user_id = session.get('user_id')
    if not user_id: return redirect(url_for('login'))
    
    show_mature = request.form.get('show_mature') == 'true'
    language = request.form.get('language', 'en')
    text_size = request.form.get('text_size', 'medium')
    
    try:
        supabase.table('users').update({
            "show_mature": show_mature,
            "language": language,
            "text_size": text_size
        }).eq('id', user_id).execute()
        return redirect(url_for('profile'))
    except Exception as e:
        return f"Error updating settings: {e}"

@app.route('/agree-to-tos', methods=['POST'])
def agree_to_tos():
    user_id = session.get('user_id')
    if not user_id: return redirect(url_for('login'))

    try:
        supabase.table('users').update({"agreed_to_tos": True}).eq('id', user_id).execute()
        return redirect(request.referrer or url_for('home'))
    except Exception as e:
        return f"Error: {e}"
    
@app.route('/quick-add-draft', methods=['POST'])
def quick_add_draft():
    import re # Forced import inside the function so it can't be missed
    
    user_id = session.get('user_id')
    if not user_id: return redirect(url_for('login'))

    # Safety Net 1: Admin Check
    try:
        user = supabase.table('users').select('role').eq('id', user_id).single().execute()
        if user.data.get('role') not in ['owner', 'admin']: return "Access Denied", 403
    except Exception as e:
        return f"Authentication Error: {e}", 403

    # Safety Net 2: The Data Parser
    try:
        category = request.form.get('category', 'game')
        raw_input = request.form.get('raw_input', '').strip()
        
        title = raw_input
        release_year = None
        
        if ',' in raw_input:
            parts = raw_input.rsplit(',', 1)
            title = parts[0].strip()
            year_str = parts[1].strip()
            if year_str.isdigit():
                release_year = int(year_str)
                
        slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
        placeholder_text = title.replace(' ', '+')[:15]
        cover_image_url = f"https://via.placeholder.com/150x210/1e1e1e/88C0D0?text={placeholder_text}"

        payload = {
            "title": safe_censor(title),
            "slug": slug,
            "category": category,
            "status": "draft",
            "author_id": user_id,
            "content": "Score and review coming soon...",
            "tldr": "Placeholder for an upcoming review.",
            "staff_score": 0,
            "granular_scores": {},
            "rating": 0,
            "release_year": release_year,
            "cover_image_url": cover_image_url,
            "tags": [],               # Added to prevent SQL NOT NULL panic
            "is_controversial": False # Added to prevent SQL NOT NULL panic
        }

        supabase.table('reviews').insert(payload).execute()
        return redirect(url_for('create_review_page'))
    
    # If it crashes now, it will print the EXACT reason on your screen!
    except Exception as e:
        return f"SYSTEM CRASH LOG: {str(e)}", 500

# --- STAFF CREATION ENGINE ---

@app.route('/create-review')
def create_review_page():
    user_id = session.get('user_id')
    if not user_id: return redirect(url_for('login'))
    
    user = supabase.table('users').select('role').eq('id', user_id).single().execute()
    if user.data.get('role') not in ['owner', 'admin']:
        return "Access Denied: Staff Only", 403

    return render_template('create_review.html', review=None)

@app.route('/edit-review/<slug>')
def edit_review_page(slug):
    user_id = session.get('user_id')
    if not user_id: return redirect(url_for('login'))

    user = supabase.table('users').select('role').eq('id', user_id).single().execute()
    if user.data.get('role') not in ['owner', 'admin']:
        return "Access Denied", 403

    try:
        response = supabase.table('reviews').select('*').eq('slug', slug).single().execute()
        return render_template('create_review.html', review=response.data)
    except Exception as e:
        return f"Error loading review for editing: {e}"

@app.route('/submit-review', methods=['POST'])
def submit_review():
    user_id = session.get('user_id')
    if not user_id: return redirect(url_for('login'))

    original_slug = request.form.get('original_slug')
    category = request.form.get('category')
    
    title = safe_censor(request.form.get('title'))
    content = safe_censor(request.form.get('content'))
    tldr = safe_censor(request.form.get('tldr'))
    tags_input = safe_censor(request.form.get('tags', ''))
    
    slug = request.form.get('slug')
    cover_image_url = request.form.get('cover_image_url')
    action = request.form.get('action')
    is_controversial = request.form.get('is_controversial') == 'on'
    
    # NEW: Capture Release Year
    release_year = request.form.get('release_year', type=int)
    
    review_tags = [t.strip().lower() for t in tags_input.split(',') if t.strip()]
    
    for t in review_tags:
        try: supabase.table('tags').insert({"name": t}).execute()
        except: pass
    
    status = 'published' if action == 'post' else 'draft'

    granular_scores = {}
    if category == 'game':
        granular_scores = {
            "gameplay": int(request.form.get('g_gameplay', 5)), "visuals": int(request.form.get('g_visuals', 5)),
            "audio": int(request.form.get('g_audio', 5)), "narrative": int(request.form.get('g_narrative', 5)),
            "replayability": int(request.form.get('g_replayability', 5))
        }
    else:
        granular_scores = {
            "narrative": int(request.form.get('m_narrative', 5)), "performances": int(request.form.get('m_performances', 5)),
            "cinematography": int(request.form.get('m_cinematography', 5)), "audio": int(request.form.get('m_audio', 5)),
            "direction": int(request.form.get('m_direction', 5))
        }

    staff_score = sum(granular_scores.values())
    legacy_rating = staff_score / 5.0 

    # NEW: Added release_year to payload
    payload = {
        "category": category, "title": title, "slug": slug, "cover_image_url": cover_image_url,
        "content": content, "tldr": tldr, "staff_score": staff_score, "granular_scores": granular_scores,
        "rating": legacy_rating, "author_id": user_id, "status": status, "is_controversial": is_controversial,
        "tags": review_tags, "release_year": release_year
    }

    try:
        if original_slug:
            supabase.table('reviews').update(payload).eq('slug', original_slug).execute()
        else:
            supabase.table('reviews').insert(payload).execute()
        return redirect(url_for('home'))
    except Exception as e:
        return f"Error submitting review: {e}"

# --- COMMUNITY SUGGESTION ENGINE ---

@app.route('/suggest-review')
def suggest_review_page():
    user_id = session.get('user_id')
    if not user_id: return redirect(url_for('login'))
    return render_template('suggest_review.html')

@app.route('/submit-suggestion', methods=['POST'])
def submit_suggestion():
    user_id = session.get('user_id')
    if not user_id: return redirect(url_for('login'))

    action = request.form.get('action')
    request_type = request.form.get('request_type')
    
    if action == 'draft':
        drafts_res = supabase.table('reviews').select('id', count='exact').eq('author_id', user_id).eq('status', 'draft').execute()
        if drafts_res.count >= 4:
            return "Limit Reached: You can only have a maximum of 4 active drafts.", 400

    category = request.form.get('category')
    slug = request.form.get('slug')
    status = 'pending' if action == 'submit' else 'draft'

    title = safe_censor(request.form.get('title'))
    tags_input = safe_censor(request.form.get('tags', ''))
    
    # NEW: Capture Release Year
    release_year = request.form.get('release_year', type=int)
    
    review_tags = [t.strip().lower() for t in tags_input.split(',') if t.strip()]
    for t in review_tags:
        try: supabase.table('tags').insert({"name": t}).execute()
        except: pass

    if request_type == 'basic':
        try:
            # NEW: Added release_year to insert
            supabase.table('reviews').insert({
                "category": category, "title": title, "slug": slug, "author_id": user_id, "status": status,
                "content": "User requested this review.", "staff_score": 0, "rating": 0, "tags": review_tags,
                "release_year": release_year
            }).execute()
            return redirect(url_for('home'))
        except Exception as e:
            return f"Error: {e}"

    cover_image_url = request.form.get('cover_image_url', '')
    content = safe_censor(request.form.get('content', ''))
    tldr = safe_censor(request.form.get('tldr', ''))

    granular_scores = {}
    if category == 'game':
        granular_scores = { "gameplay": int(request.form.get('g_gameplay', 5)), "visuals": int(request.form.get('g_visuals', 5)), "audio": int(request.form.get('g_audio', 5)), "narrative": int(request.form.get('g_narrative', 5)), "replayability": int(request.form.get('g_replayability', 5)) }
    else:
        granular_scores = { "narrative": int(request.form.get('m_narrative', 5)), "performances": int(request.form.get('m_performances', 5)), "cinematography": int(request.form.get('m_cinematography', 5)), "audio": int(request.form.get('m_audio', 5)), "direction": int(request.form.get('m_direction', 5)) }

    staff_score = sum(granular_scores.values())
    
    try:
        # NEW: Added release_year to insert
        supabase.table('reviews').insert({
            "category": category, "title": title, "slug": slug,
            "cover_image_url": cover_image_url, "content": content, "tldr": tldr,
            "staff_score": staff_score, "granular_scores": granular_scores,
            "rating": staff_score / 5.0, "author_id": user_id, "status": status, "tags": review_tags,
            "release_year": release_year
        }).execute()
        return redirect(url_for('home'))
    except Exception as e:
        return f"Error: {e}"

@app.route('/review/<slug>')
def review_page(slug):
    user_id = session.get('user_id')
    user_role = 'user'
    text_size = 'medium' # Default
    
    if user_id:
        try:
            res = supabase.table('users').select('role, text_size').eq('id', user_id).single().execute()
            user_role = res.data.get('role', 'user')
            text_size = res.data.get('text_size', 'medium')
        except: pass
        
    seo_data = {"title": "Nord Reviews", "tldr": "Read the full review and community scores.", "cover_image_url": ""}
    try:
        res = supabase.table('reviews').select('title, tldr, cover_image_url').eq('slug', slug).single().execute()
        if res.data:
            seo_data = res.data
    except: pass

    return render_template('review.html', slug=slug, user_role=user_role, seo=seo_data, text_size=text_size, current_user_id=user_id)

# --- STAFF INBOX ---

@app.route('/staff-inbox')
def staff_inbox():
    user_id = session.get('user_id')
    if not user_id: return redirect(url_for('login'))

    user = supabase.table('users').select('role').eq('id', user_id).single().execute()
    if user.data.get('role') not in ['owner', 'admin']: return "Access Denied: Staff Only", 403

    try:
        reviews_res = supabase.table('reviews').select('*, users(username)').eq('status', 'pending').order('created_at', desc=True).execute()
        reports_res = supabase.table('reports').select('*, users(username)').eq('status', 'pending').order('created_at', desc=True).execute()
        return render_template('inbox.html', reviews=reviews_res.data, reports=reports_res.data)
    except Exception as e:
        return f"Error loading inbox: {e}"

@app.route('/approve-review/<slug>', methods=['POST'])
def approve_review(slug):
    user_id = session.get('user_id')
    if not user_id: return redirect(url_for('login'))

    user = supabase.table('users').select('role').eq('id', user_id).single().execute()
    if user.data.get('role') not in ['owner', 'admin']: return "Access Denied", 403

    try:
        # 1. Find out who wrote it before we approve it
        review = supabase.table('reviews').select('author_id').eq('slug', slug).single().execute()
        author_id = review.data.get('author_id')
        
        # 2. Approve it
        supabase.table('reviews').update({"status": "published"}).eq('slug', slug).execute()
        
        # 3. Reward the author with a massive XP boost!
        if author_id:
            author_data = supabase.table('users').select('approved_suggestions').eq('id', author_id).single().execute()
            new_count = author_data.data.get('approved_suggestions', 0) + 1
            supabase.table('users').update({'approved_suggestions': new_count}).eq('id', author_id).execute()
            update_user_level(author_id)
            
        return redirect(url_for('staff_inbox'))
    except Exception as e:
        return f"Error approving review: {e}"

@app.route('/resolve-report/<report_id>', methods=['POST'])
def resolve_report(report_id):
    user_id = session.get('user_id')
    if not user_id: return redirect(url_for('login'))

    user = supabase.table('users').select('role').eq('id', user_id).single().execute()
    if user.data.get('role') not in ['owner', 'admin']: return "Access Denied", 403

    try:
        supabase.table('reports').update({"status": "resolved"}).eq('id', report_id).execute()
        return redirect(url_for('staff_inbox'))
    except Exception as e:
        return f"Error resolving report: {e}"

# --- COMMUNITY VOTING ENGINE ---

@app.route('/submit-vote', methods=['POST'])
def submit_vote():
    user_id = session.get('user_id')
    if not user_id: return redirect(url_for('login'))

    slug = request.form.get('slug')
    category = request.form.get('category')
    
    if category == 'game':
        total_score = sum([int(request.form.get('g_gameplay', 5)), int(request.form.get('g_visuals', 5)), int(request.form.get('g_audio', 5)), int(request.form.get('g_narrative', 5)), int(request.form.get('g_replayability', 5))])
    else:
        total_score = sum([int(request.form.get('m_narrative', 5)), int(request.form.get('m_performances', 5)), int(request.form.get('m_cinematography', 5)), int(request.form.get('m_audio', 5)), int(request.form.get('m_direction', 5))])

    try:
        existing_vote = supabase.table('votes').select('*').eq('review_slug', slug).eq('user_id', user_id).execute()
        
        if len(existing_vote.data) > 0:
            vote_id = existing_vote.data[0]['id']
            supabase.table('votes').update({'total_score': total_score}).eq('id', vote_id).execute()
        else:
            supabase.table('votes').insert({'review_slug': slug, 'user_id': user_id, 'total_score': total_score}).execute()
            
            # NEW: Reward the user for their FIRST vote on this review!
            user_data = supabase.table('users').select('vote_count').eq('id', user_id).single().execute()
            new_vote_count = user_data.data.get('vote_count', 0) + 1
            supabase.table('users').update({'vote_count': new_vote_count}).eq('id', user_id).execute()
            update_user_level(user_id)

        all_votes = supabase.table('votes').select('total_score').eq('review_slug', slug).execute()
        vote_count = len(all_votes.data)
        community_score = sum(v['total_score'] for v in all_votes.data) / vote_count if vote_count > 0 else 0

        supabase.table('reviews').update({'community_score': round(community_score, 1), 'vote_count': vote_count}).eq('slug', slug).execute()
        return redirect(url_for('review_page', slug=slug))
    except Exception as e:
        return f"Error submitting vote: {e}"

# --- CORE API ROUTES ---

@app.route('/moderate-user/<target_username>', methods=['POST'])
def moderate_user(target_username):
    user_id = session.get('user_id')
    if not user_id: return redirect(url_for('login'))
    
    try:
        # Check if caller is staff
        caller = supabase.table('users').select('role').eq('id', user_id).single().execute()
        caller_role = caller.data.get('role')
        
        if caller_role not in ['owner', 'admin', 'moderator']:
            return "Access Denied", 403
            
        new_status = request.form.get('status')
        
        # Enforce Role Hierarchy (Moderators can only mute)
        if caller_role == 'moderator' and new_status != 'muted':
            return "Moderators are only authorized to Mute accounts.", 403

        if new_status in ['active', 'muted', 'banned']:
            supabase.table('users').update({'account_status': new_status}).eq('username', target_username).execute()
            
        # BULLETPROOF REDIRECT: Send them right back to where they clicked the button
        if request.referrer:
            return redirect(request.referrer)
            
        return redirect(f"/user/{target_username}")
    except Exception as e:
        return f"Error modifying user: {e}"

def award_xp(user_id, amount):
    """Calculates and updates user XP and Level automatically."""
    try:
        user = supabase.table('users').select('xp, level').eq('id', user_id).single().execute()
        current_xp = user.data.get('xp') or 0
        new_xp = current_xp + amount
        if new_xp < 0: 
            new_xp = 0 # Prevent negative XP
        
        # Every 100 XP is a Level
        new_level = (new_xp // 100) + 1
        supabase.table('users').update({'xp': new_xp, 'level': new_level}).eq('id', user_id).execute()
    except Exception as e:
        print(f"XP Error: {e}")

@app.route('/submit-comment', methods=['POST'])
def submit_comment():
    user_id = session.get('user_id')
    if not user_id: return redirect(url_for('login'))

    # SECURITY CHECK: Is user muted or banned?
    status_check = supabase.table('users').select('account_status').eq('id', user_id).single().execute()
    if status_check.data.get('account_status') in ['muted', 'banned']:
        return "Your account has been restricted by Staff.", 403

    slug = request.form.get('slug')
    content = safe_censor(request.form.get('content'))
    parent_id = request.form.get('parent_id') # Might be None if it's a normal comment

    try:
        data = {
            "review_slug": slug,
            "author_id": user_id,
            "content": content
        }
        if parent_id:
            data['parent_id'] = parent_id

        supabase.table('comments').insert(data).execute()
        
        # Grant 10 XP for commenting!
        award_xp(user_id, 10)
        
        return redirect(url_for('review_page', slug=slug))
    except Exception as e:
        return f"Error submitting comment: {e}"

@app.route('/vote-comment/<comment_id>', methods=['POST'])
def vote_comment(comment_id):
    user_id = session.get('user_id')
    if not user_id: return "Must be logged in", 403
    
    vote_type = request.form.get('vote_type') # 'up' or 'down'
    vote_val = 1 if vote_type == 'up' else -1
    
    try:
        # 1. Fetch the comment details
        comment = supabase.table('comments').select('upvotes, downvotes, author_id').eq('id', comment_id).single().execute()
        author_id = comment.data.get('author_id')
        
        # EXPLOIT PATCH: You cannot vote on your own comment!
        if user_id == author_id:
            return redirect(request.referrer)

        # 2. Check if user already voted on this comment
        existing = supabase.table('comment_votes').select('*').eq('comment_id', comment_id).eq('user_id', user_id).execute()
        
        upvotes = comment.data.get('upvotes') or 0
        downvotes = comment.data.get('downvotes') or 0
        
        if existing.data:
            return redirect(request.referrer) # Prevent double voting

        # 3. Record the vote
        supabase.table('comment_votes').insert({"comment_id": comment_id, "user_id": user_id, "vote_value": vote_val}).execute()
        
        # 4. Update the comment totals and author's XP
        if vote_val == 1:
            supabase.table('comments').update({'upvotes': upvotes + 1}).eq('id', comment_id).execute()
            award_xp(author_id, 2) # +2 XP for a Like
        else:
            supabase.table('comments').update({'downvotes': downvotes + 1}).eq('id', comment_id).execute()
            award_xp(author_id, -1) # -1 XP for a Dislike

        return redirect(request.referrer)
    except Exception as e:
        return f"Error voting: {e}"

@app.route('/delete-comment/<comment_id>', methods=['POST'])
def delete_comment(comment_id):
    user_id = session.get('user_id')
    if not user_id: return redirect(url_for('login'))
    
    slug = request.form.get('slug')
    
    try:
        # Check permissions: Is it their comment, or are they Staff?
        user = supabase.table('users').select('role').eq('id', user_id).single().execute()
        user_role = user.data.get('role')
        
        comment = supabase.table('comments').select('author_id').eq('id', comment_id).single().execute()
        comment_author = comment.data.get('author_id')
        
        if user_id == comment_author or user_role in ['owner', 'admin']:
            supabase.table('comments').delete().eq('id', comment_id).execute()
            
        return redirect(url_for('review_page', slug=slug))
    except Exception as e:
        return f"Error deleting comment: {e}"

@app.route('/edit-comment/<comment_id>', methods=['POST'])
def edit_comment(comment_id):
    user_id = session.get('user_id')
    if not user_id: return redirect(url_for('login'))
    
    slug = request.form.get('slug')
    new_content = safe_censor(request.form.get('content'))
    
    try:
        # Security: Only the original author can edit a comment
        comment = supabase.table('comments').select('author_id').eq('id', comment_id).single().execute()
        if user_id == comment.data.get('author_id'):
            supabase.table('comments').update({"content": new_content}).eq('id', comment_id).execute()
            
        return redirect(url_for('review_page', slug=slug))
    except Exception as e:
        return f"Error editing comment: {e}"


@app.route('/submit-report', methods=['POST'])
def submit_report():
    user_id = session.get('user_id')
    if not user_id: return redirect(url_for('login'))

    reported_username = request.form.get('reported_username')
    reason = safe_censor(request.form.get('reason'))
    slug = request.form.get('slug') 

    try:
        supabase.table('reports').insert({
            "reporter_id": user_id,
            "reported_username": reported_username,
            "reason": reason
        }).execute()
        return redirect(url_for('review_page', slug=slug))
    except Exception as e:
        return f"Error submitting report: {e}"

@app.route('/delete-review/<slug>', methods=['POST'])
def delete_review(slug):
    user_id = session.get('user_id')
    if not user_id: return redirect(url_for('login'))
    
    user = supabase.table('users').select('role').eq('id', user_id).single().execute()
    if user.data.get('role') not in ['owner', 'admin']: return "Access Denied", 403
        
    try:
        supabase.table('reviews').delete().eq('slug', slug).execute()
        return redirect(request.referrer or url_for('home'))
    except Exception as e:
        return f"Error deleting review: {e}"

@app.route('/toggle-controversy/<slug>', methods=['POST'])
def toggle_controversy(slug):
    user_id = session.get('user_id')
    if not user_id: return redirect(url_for('login'))
    
    user = supabase.table('users').select('role').eq('id', user_id).single().execute()
    if user.data.get('role') not in ['owner', 'admin']: return "Access Denied", 403
        
    try:
        review = supabase.table('reviews').select('is_controversial').eq('slug', slug).single().execute()
        current_status = review.data.get('is_controversial', False)
        supabase.table('reviews').update({"is_controversial": not current_status}).eq('slug', slug).execute()
        return redirect(url_for('review_page', slug=slug))
    except Exception as e:
        return f"Error toggling controversy: {e}"

@app.route('/test-db')
def test_db():
    try:
        response = supabase.table('reviews').select("*").limit(1).execute()
        return jsonify({"status": "success", "data": response.data})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route('/api/reviews/<category>')
def get_reviews_by_category(category):
    valid_categories = ['game', 'movie', 'tv', 'book']
    if category not in valid_categories:
        return jsonify({"status": "error", "message": "Invalid category"}), 400

    user_id = session.get('user_id')
    user_role = 'guest'
    show_mature = False # Default to Safe For Work for guests

    if user_id:
        try:
            res = supabase.table('users').select('role, show_mature').eq('id', user_id).single().execute()
            user_role = res.data.get('role', 'user')
            show_mature = res.data.get('show_mature', False)
        except: pass

    try:
        query = supabase.table('reviews').select('*, users(username, profile_image_url, level)').eq('category', category)
        
        # THE FIX: Guests ONLY see published. Logged-in users see published + drafts.
        # We use .in_() to ensure 'pending' community suggestions never leak onto the feed.
        if not user_id:
            query = query.eq('status', 'published')
        else:
            query = query.in_('status', ['published', 'draft'])
            
        response = query.order('created_at', desc=True).execute()
        reviews = response.data
        
        # Filter out mature content if user hasn't opted in (and isn't staff)
        if not show_mature and user_role not in ['owner', 'admin']:
            safe_reviews = []
            mature_tags = ['nsfw', '18+', 'mature']
            for r in reviews:
                r_tags = r.get('tags') or []
                if not any(t in r_tags for t in mature_tags):
                    safe_reviews.append(r)
            reviews = safe_reviews

        # SECURITY PATCH: Strip the actual text from drafts if the user isn't staff.
        # This prevents tech-savvy users from inspecting the page code to read reviews early!
        if user_role not in ['owner', 'admin']:
            for r in reviews:
                if r.get('status') == 'draft':
                    r['content'] = "Nice try! This review isn't finished yet."
                    r['tldr'] = "Nice try! This review isn't finished yet."

        return jsonify({"status": "success", "data": reviews})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route('/api/review/<slug>')
def get_single_review(slug):
    try:
        response = supabase.table('reviews').select('*, users(username, profile_image_url, level)').eq('slug', slug).single().execute()
        review_data = response.data
        
        # NEW: Fetch all comments for this review, including the author's details
        comments_res = supabase.table('comments').select('*, users(username, profile_image_url, level, rank_name)').eq('review_slug', slug).order('created_at', desc=True).execute()
        review_data['comments'] = comments_res.data
        
        user_id = session.get('user_id')
        user_role = 'user'
        show_mature = False

        if user_id:
            try:
                res = supabase.table('users').select('role, show_mature').eq('id', user_id).single().execute()
                user_role = res.data.get('role', 'user')
                show_mature = res.data.get('show_mature', False)
            except: pass
            
        # Security check 1: Block Drafts from non-staff
        if review_data.get('status') == 'draft' and user_role not in ['owner', 'admin']:
            return jsonify({"status": "error", "message": "Access Denied"}), 403
            
        # Security check 2: Block direct URLs to NSFW content if not opted in
        mature_tags = ['nsfw', '18+', 'mature']
        r_tags = review_data.get('tags') or []
        if any(t in r_tags for t in mature_tags) and not show_mature and user_role not in ['owner', 'admin']:
            return jsonify({"status": "error", "message": "Content restricted. Please enable Mature Content in your profile."}), 403
             
        return jsonify({"status": "success", "data": review_data})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Review not found: {str(e)}"}), 404

if __name__ == '__main__':
    app.run(debug=True, port=5000)