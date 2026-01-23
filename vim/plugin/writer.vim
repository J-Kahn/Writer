" Writer.vim - Vim integration for Writer environment
" Communicates with side panels via files in ~/.writer/

if exists('g:loaded_writer')
    finish
endif
let g:loaded_writer = 1

" ============================================================================
" Configuration
" ============================================================================

let g:writer_dir = expand('~/.writer')
let g:writer_context_file = g:writer_dir . '/context.json'
let g:writer_preview_file = g:writer_dir . '/preview_state.json'
let g:writer_enabled = 1
let g:writer_python_dir = ''

" Preview state
let s:preview_active = 0
let s:preview_text = ''
let s:preview_line = 0
let s:preview_ns = 0

" ============================================================================
" Setup Function (called by launcher)
" ============================================================================

function! writer#Setup(python_dir, filename) abort
    let g:writer_python_dir = a:python_dir

    " Ensure directory exists
    call mkdir(g:writer_dir, 'p')

    " Create namespace for virtual text if available
    if has('nvim')
        let s:preview_ns = nvim_create_namespace('writer_preview')
    endif

    " Write initial context
    call s:WriteContext()

    " Set up autocommands
    call s:SetupAutocommands()

    echo "Writer: Ready. <Leader>ws suggestions, <Leader>wf fill, <Leader>wr review."
endfunction

" ============================================================================
" Context Writing
" ============================================================================

function! s:WriteContext() abort
    if !g:writer_enabled
        return
    endif

    let l:lines = getline(1, '$')
    let l:cursor_line = line('.')
    let l:cursor_col = col('.')

    " Get context around cursor
    let l:start = max([1, l:cursor_line - 50])
    let l:end = min([len(l:lines), l:cursor_line + 10])

    let l:context = {
        \ 'lines': l:lines,
        \ 'cursor_line': l:cursor_line,
        \ 'cursor_col': l:cursor_col,
        \ 'before': l:lines[l:start-1 : l:cursor_line-2],
        \ 'current': get(l:lines, l:cursor_line-1, ''),
        \ 'after': l:lines[l:cursor_line : l:end-1],
        \ 'filename': expand('%:p'),
        \ 'timestamp': localtime()
        \ }

    call writefile([json_encode(l:context)], g:writer_context_file)
endfunction

" ============================================================================
" Outline Extraction (for fill section)
" ============================================================================

function! s:GetDocumentOutline() abort
    let l:outline = []
    let l:lines = getline(1, '$')

    for l:line in l:lines
        " Match markdown headings
        let l:match = matchlist(l:line, '^\(#\+\)\s\+\(.*\)$')
        if !empty(l:match)
            call add(l:outline, l:match[2])
        endif
    endfor

    return l:outline
endfunction

function! s:GetCurrentHeading() abort
    " Find the heading above current cursor position
    let l:cur_line = line('.')

    for l:lnum in range(l:cur_line, 1, -1)
        let l:line = getline(l:lnum)
        let l:match = matchlist(l:line, '^\(#\+\)\s\+\(.*\)$')
        if !empty(l:match)
            return {'line': l:lnum, 'level': len(l:match[1]), 'text': l:match[2]}
        endif
    endfor

    return {}
endfunction

" ============================================================================
" Preview Functions
" ============================================================================

function! s:ShowPreview() abort
    " Read preview state
    if !filereadable(g:writer_preview_file)
        return
    endif

    let l:content = join(readfile(g:writer_preview_file), '')
    let l:state = json_decode(l:content)

    if empty(l:state) || empty(get(l:state, 'text', ''))
        return
    endif

    let s:preview_text = l:state.text
    let s:preview_line = line('.')
    let s:preview_active = 1

    " Show preview using virtual text (Neovim) or echo (Vim)
    if has('nvim')
        call s:ShowVirtualTextPreview()
    else
        call s:ShowPopupPreview()
    endif
endfunction

function! s:ShowVirtualTextPreview() abort
    " Clear previous
    call nvim_buf_clear_namespace(0, s:preview_ns, 0, -1)

    " Add virtual text after current line
    let l:preview_lines = split(s:preview_text, '\n')
    let l:display_text = ' ' . l:preview_lines[0]
    if len(l:preview_lines) > 1
        let l:display_text .= ' [+' . (len(l:preview_lines) - 1) . ' lines]'
    endif

    call nvim_buf_set_extmark(0, s:preview_ns, s:preview_line - 1, 0, {
        \ 'virt_text': [[l:display_text, 'Comment']],
        \ 'virt_text_pos': 'eol'
        \ })
endfunction

function! s:ShowPopupPreview() abort
    " For regular Vim, show in a popup or echo
    if exists('*popup_create')
        " Close existing popup
        call popup_clear()

        let l:preview_lines = split(s:preview_text, '\n')
        " Limit preview length
        if len(l:preview_lines) > 5
            let l:preview_lines = l:preview_lines[:4] + ['...']
        endif

        call popup_create(l:preview_lines, {
            \ 'line': 'cursor+1',
            \ 'col': 'cursor',
            \ 'border': [],
            \ 'padding': [0, 1, 0, 1],
            \ 'highlight': 'Pmenu',
            \ 'borderhighlight': ['Comment'],
            \ 'close': 'click',
            \ 'moved': 'any'
            \ })
    else
        " Fallback to echo
        let l:short = s:preview_text[:80]
        if len(s:preview_text) > 80
            let l:short .= '...'
        endif
        echo "Preview: " . l:short
    endif
endfunction

function! s:ClearPreview() abort
    let s:preview_active = 0
    let s:preview_text = ''

    if has('nvim')
        call nvim_buf_clear_namespace(0, s:preview_ns, 0, -1)
    elseif exists('*popup_clear')
        call popup_clear()
    endif

    echo "Writer: Preview cleared"
endfunction

function! s:AcceptPreview() abort
    if !s:preview_active || empty(s:preview_text)
        echo "Writer: No preview to accept"
        return
    endif

    " Check mode
    let l:mode_file = g:writer_dir . '/suggestion_mode.txt'
    let l:mode = 'next_paragraph'
    if filereadable(l:mode_file)
        let l:mode = get(readfile(l:mode_file), 0, 'next_paragraph')
    endif

    let l:lines = split(s:preview_text, '\n')

    if l:mode == 'alternatives'
        " Replace current paragraph
        call s:ReplaceCurrentParagraph(l:lines)
        echo "Writer: Paragraph replaced"
    else
        " Insert as new paragraph
        call append(line('.'), [''] + l:lines)
        normal! j
        echo "Writer: Paragraph inserted"
    endif

    call s:ClearPreview()
endfunction

" ============================================================================
" User Commands
" ============================================================================

function! writer#RequestSuggestions() abort
    if !g:writer_enabled
        echo "Writer: Disabled"
        return
    endif

    " Write current context
    call s:WriteContext()

    " Signal suggestions panel
    let l:signal_file = g:writer_dir . '/request_suggestions'
    call writefile([string(localtime())], l:signal_file)

    echo "Writer: Requesting paragraph suggestions..."
endfunction

function! writer#RefreshOutline() abort
    call s:WriteContext()
    let l:signal_file = g:writer_dir . '/request_outline'
    call writefile([string(localtime())], l:signal_file)
    echo "Writer: Refreshing outline..."
endfunction

function! writer#FillSection() abort
    if !g:writer_enabled
        echo "Writer: Disabled"
        return
    endif

    " Get current heading
    let l:heading = s:GetCurrentHeading()
    if empty(l:heading)
        echo "Writer: No heading found. Place cursor under a heading."
        return
    endif

    " Check if section has content (non-empty lines until next heading)
    let l:has_content = 0
    let l:cur_line = l:heading.line + 1
    let l:total_lines = line('$')

    while l:cur_line <= l:total_lines
        let l:line = getline(l:cur_line)
        " Check for next heading
        if l:line =~ '^#'
            break
        endif
        " Check for non-empty content
        if l:line =~ '\S'
            let l:has_content = 1
            break
        endif
        let l:cur_line += 1
    endwhile

    if l:has_content
        let l:confirm = confirm("Section '" . l:heading.text . "' has content. Generate anyway?", "&Yes\n&No", 2)
        if l:confirm != 1
            return
        endif
    endif

    " Write current context first
    call s:WriteContext()

    " Get outline
    let l:outline = s:GetDocumentOutline()

    " Create fill request
    let l:request = {
        \ 'heading': l:heading.text,
        \ 'heading_line': l:heading.line,
        \ 'heading_level': l:heading.level,
        \ 'outline': l:outline
        \ }

    let l:request_file = g:writer_dir . '/request_fill_section'
    call writefile([json_encode(l:request)], l:request_file)

    echo "Writer: Generating content for '" . l:heading.text . "'..."
endfunction

function! writer#InsertSuggestion(num) abort
    let l:suggestion_file = g:writer_dir . '/suggestion_' . a:num . '.txt'
    let l:mode_file = g:writer_dir . '/suggestion_mode.txt'

    if !filereadable(l:suggestion_file)
        echo "Writer: No suggestion " . a:num . " available"
        return
    endif

    let l:lines = readfile(l:suggestion_file)
    if empty(l:lines)
        echo "Writer: Suggestion " . a:num . " is empty"
        return
    endif

    " Check mode
    let l:mode = 'next_paragraph'
    if filereadable(l:mode_file)
        let l:mode = get(readfile(l:mode_file), 0, 'next_paragraph')
    endif

    if l:mode == 'alternatives'
        " Replace current paragraph
        call s:ReplaceCurrentParagraph(l:lines)
        echo "Writer: Replaced paragraph with alternative " . a:num
    else
        " Insert as new paragraph after current line
        call append(line('.'), [''] + l:lines)
        normal! j
        echo "Writer: Inserted paragraph " . a:num
    endif

    " Clear preview
    call s:ClearPreview()
endfunction

function! s:ReplaceCurrentParagraph(new_lines) abort
    " Find paragraph boundaries (blank lines)
    let l:cur = line('.')
    let l:start = l:cur
    let l:end = l:cur

    " Find start of paragraph (search backwards for blank line or start of file)
    while l:start > 1
        let l:prev = getline(l:start - 1)
        if l:prev =~ '^\s*$'
            break
        endif
        let l:start -= 1
    endwhile

    " Find end of paragraph (search forwards for blank line or end of file)
    let l:total = line('$')
    while l:end < l:total
        let l:next = getline(l:end + 1)
        if l:next =~ '^\s*$'
            break
        endif
        let l:end += 1
    endwhile

    " Delete old paragraph and insert new
    execute l:start . ',' . l:end . 'delete _'
    call append(l:start - 1, a:new_lines)

    " Position cursor at start of new paragraph
    execute l:start
endfunction

function! writer#PreviewNext() abort
    let l:signal_file = g:writer_dir . '/preview_next'
    call writefile([string(localtime())], l:signal_file)

    " Wait a bit for panel to update
    sleep 100m
    call s:ShowPreview()
endfunction

function! writer#PreviewPrev() abort
    let l:signal_file = g:writer_dir . '/preview_prev'
    call writefile([string(localtime())], l:signal_file)

    " Wait a bit for panel to update
    sleep 100m
    call s:ShowPreview()
endfunction

function! writer#Toggle() abort
    let g:writer_enabled = !g:writer_enabled
    echo "Writer: " . (g:writer_enabled ? "Enabled" : "Disabled")
endfunction

function! writer#RequestReview() abort
    if !g:writer_enabled
        echo "Writer: Disabled"
        return
    endif

    " Write current context first
    call s:WriteContext()

    " Signal review panel
    let l:signal_file = g:writer_dir . '/request_review'
    call writefile([string(localtime())], l:signal_file)

    echo "Writer: Requesting document review..."
endfunction

" ============================================================================
" Autocommands
" ============================================================================

function! s:SetupAutocommands() abort
    augroup Writer
        autocmd!
        " Update context periodically and on save
        autocmd CursorHold,CursorHoldI * call s:WriteContext()
        autocmd BufWritePost * call s:WriteContext()
        autocmd TextChanged,TextChangedI * call s:WriteContext()

        " Clear preview on cursor move
        autocmd CursorMoved,CursorMovedI * if s:preview_active && line('.') != s:preview_line | call s:ClearPreview() | endif

        " Refresh preview display periodically
        autocmd CursorHold * if s:preview_active | call s:ShowPreview() | endif
    augroup END
endfunction

" ============================================================================
" Keybindings
" ============================================================================

" Suggestions
nnoremap <silent> <Leader>ws :call writer#RequestSuggestions()<CR>
nnoremap <silent> <Leader>w1 :call writer#InsertSuggestion(1)<CR>
nnoremap <silent> <Leader>w2 :call writer#InsertSuggestion(2)<CR>
nnoremap <silent> <Leader>w3 :call writer#InsertSuggestion(3)<CR>

" Preview cycling
nnoremap <silent> <Leader>wn :call writer#PreviewNext()<CR>
nnoremap <silent> <Leader>wp :call writer#PreviewPrev()<CR>
nnoremap <silent> <Leader>wa :call <SID>AcceptPreview()<CR>
nnoremap <silent> <Leader>wc :call <SID>ClearPreview()<CR>

" Outline
nnoremap <silent> <Leader>wo :call writer#RefreshOutline()<CR>
nnoremap <silent> <Leader>wf :call writer#FillSection()<CR>

" Review
nnoremap <silent> <Leader>wr :call writer#RequestReview()<CR>

" Toggle
nnoremap <silent> <Leader>wt :call writer#Toggle()<CR>

" ============================================================================
" Model Selection
" ============================================================================

let s:openai_models = ['gpt-5.2', 'gpt-5', 'gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'gpt-4', 'gpt-3.5-turbo', 'o1', 'o1-mini', 'o1-preview', 'o3-mini']

function! writer#SetModel(model) abort
    let l:model_file = g:writer_dir . '/model_override.json'
    let l:override = {'openai_model': a:model}
    call writefile([json_encode(l:override)], l:model_file)
    echo "Writer: Model set to " . a:model
endfunction

function! writer#GetModel() abort
    let l:model_file = g:writer_dir . '/model_override.json'
    if filereadable(l:model_file)
        let l:content = join(readfile(l:model_file), '')
        let l:override = json_decode(l:content)
        return get(l:override, 'openai_model', 'default')
    endif
    return 'default (from config)'
endfunction

function! s:ModelComplete(ArgLead, CmdLine, CursorPos) abort
    return filter(copy(s:openai_models), 'v:val =~ "^" . a:ArgLead')
endfunction

" ============================================================================
" Commands
" ============================================================================

command! WriterSuggest call writer#RequestSuggestions()
command! WriterRefresh call writer#RefreshOutline()
command! WriterFill call writer#FillSection()
command! WriterReview call writer#RequestReview()
command! WriterToggle call writer#Toggle()
command! WriterPreviewNext call writer#PreviewNext()
command! WriterPreviewPrev call writer#PreviewPrev()
command! WriterAccept call <SID>AcceptPreview()
command! WriterClear call <SID>ClearPreview()
command! -nargs=1 -complete=customlist,<SID>ModelComplete WriterModel call writer#SetModel(<q-args>)
command! WriterModelShow echo "Writer: Current model is " . writer#GetModel()

" Set updatetime for responsive CursorHold
if &updatetime > 1000
    set updatetime=1000
endif
