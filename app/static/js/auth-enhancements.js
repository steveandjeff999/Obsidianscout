// Small enhancements for auth forms: password visibility toggles and simple validation
(function(){
    function toggleInputVisibility(buttonId, inputSelector){
        const btn = document.getElementById(buttonId);
        if(!btn) return;
        btn.addEventListener('click', function(e){
            e.preventDefault();
            const input = btn.closest('.input-group').querySelector(inputSelector);
            if(!input) return;
            if(input.type === 'password'){
                input.type = 'text';
                btn.innerHTML = '<i class="fas fa-eye-slash"></i>';
                btn.setAttribute('aria-pressed','true');
            } else {
                input.type = 'password';
                btn.innerHTML = '<i class="fas fa-eye"></i>';
                btn.setAttribute('aria-pressed','false');
            }
            input.focus();
        });
    }

    // Attach common toggles
    document.addEventListener('DOMContentLoaded', function(){
        toggleInputVisibility('togglePassword', 'input#password');
        toggleInputVisibility('toggleRegPassword', 'input#password');
        toggleInputVisibility('toggleRegConfirm', 'input#confirm_password');
        toggleInputVisibility('toggleResetPass', 'input#password');
        toggleInputVisibility('toggleResetConfirm', 'input#confirm');

        // Basic client-side validation: ensure password & confirm match on registration & reset
        var regForm = document.getElementById('registerForm');
        if(regForm){
            regForm.addEventListener('submit', function(ev){
                var pw = document.getElementById('password');
                var conf = document.getElementById('confirm_password');
                if(pw && conf && pw.value !== conf.value){
                    ev.preventDefault();
                    ev.stopPropagation();
                    conf.focus();
                    // show a simple inline error
                    showInlineError(conf, 'Passwords do not match');
                    return;
                }
            });
        }

        var resetForm = document.getElementById('resetForm');
        if(resetForm){
            resetForm.addEventListener('submit', function(ev){
                var pw = document.getElementById('password');
                var conf = document.getElementById('confirm');
                if(pw && conf && pw.value !== conf.value){
                    ev.preventDefault();
                    ev.stopPropagation();
                    conf.focus();
                    showInlineError(conf, 'Passwords do not match');
                    return;
                }
            });
        }

        function showInlineError(inputEl, message){
            // remove existing
            var old = inputEl.parentNode.querySelector('.invalid-feedback');
            if(old) old.remove();
            inputEl.classList.add('is-invalid');
            var div = document.createElement('div');
            div.className = 'invalid-feedback';
            div.textContent = message;
            inputEl.parentNode.appendChild(div);
            setTimeout(function(){ try{ inputEl.classList.remove('is-invalid'); if(div && div.parentNode) div.parentNode.removeChild(div); }catch(e){} }, 4000);
        }

        // Progressive enhancement: simple HTML5 form validation styling
        Array.prototype.slice.call(document.querySelectorAll('form.needs-validation')).forEach(function(form){
            form.addEventListener('submit', function(event){
                if (!form.checkValidity()){
                    event.preventDefault();
                    event.stopPropagation();
                }
                form.classList.add('was-validated');
            }, false);
        });

    });
})();
